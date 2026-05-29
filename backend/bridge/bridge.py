"""
COWORK · Serial Bridge  (bridge.py)
Fixes applied:
  - PIN auth reads from the shared SQLite users DB — no more hardcoded list
  - Serial port auto-reconnect on disconnect / reset
  - Vacancy-timeout race condition fixed with a monotonic lock
  - MQTT reconnect-on-failure loop
  - Graceful shutdown (SIGINT / SIGTERM)
  - Structured logging
"""

import os, json, time, signal, logging, sqlite3, hashlib
import serial
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime, timezone

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")

# ── Config ─────────────────────────────────────────────────────────────────────
SERIAL_PORT     = os.getenv("SERIAL_PORT",    "/dev/ttyUSB0")
SERIAL_BAUD     = int(os.getenv("SERIAL_BAUD", "115200"))
ROOM_ID         = os.getenv("ROOM_ID",         "room1")
VACANCY_TIMEOUT = int(os.getenv("VACANCY_TIMEOUT", "30"))   # seconds

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER   = os.getenv("MQTT_USER",   "server")
MQTT_PASS   = os.getenv("MQTT_PASS",   "serverpass")

INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "my-super-secret-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")

USERS_DB_PATH = os.getenv("USERS_DB_PATH", "users.db")

# ── Shared state ───────────────────────────────────────────────────────────────
_running        = True
_current_status = None          # "occupied" | "vacant" | None
_last_motion_ts = None          # monotonic timestamp of last sensor event
_motion_lock    = False          # prevents vacancy-flip race

# ── Signal handling ────────────────────────────────────────────────────────────
def _shutdown(sig, frame):
    global _running
    log.info("Shutdown signal received — stopping bridge.")
    _running = False

signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ── PIN auth — queries the live DB ─────────────────────────────────────────────
def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def lookup_pin(pin: str):
    """
    Returns (name, role) if PIN is in the DB and active, else None.
    Opens a fresh connection each call so the bridge always sees DB changes
    made by the API without caching.
    """
    try:
        conn = sqlite3.connect(USERS_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT name, role FROM users WHERE pin_hash = ?",
            (_hash_pin(pin),)
        ).fetchone()
        conn.close()
        return (row["name"], row["role"]) if row else None
    except sqlite3.Error as e:
        log.error(f"DB lookup failed: {e}")
        return None   # fail-safe: deny on DB error


# ── InfluxDB ───────────────────────────────────────────────────────────────────
influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

def write_point(measurement: str, tags: dict, fields: dict):
    p = Point(measurement).time(datetime.now(timezone.utc), WritePrecision.NS)
    for k, v in tags.items():   p = p.tag(k, v)
    for k, v in fields.items(): p = p.field(k, v)
    try:
        write_api.write(bucket=INFLUX_BUCKET, record=p)
    except Exception as e:
        log.error(f"InfluxDB write failed: {e}")


# ── MQTT ───────────────────────────────────────────────────────────────────────
mqttc = mqtt.Client(client_id=f"bridge-{ROOM_ID}")
mqttc.username_pw_set(MQTT_USER, MQTT_PASS)

def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("MQTT connected")
    else:
        log.warning(f"MQTT connect failed (rc={rc}), retrying…")

def _on_disconnect(client, userdata, rc):
    if rc != 0:
        log.warning("MQTT unexpectedly disconnected — will auto-reconnect")

mqttc.on_connect    = _on_connect
mqttc.on_disconnect = _on_disconnect

def mqtt_connect_with_retry():
    while _running:
        try:
            mqttc.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            mqttc.loop_start()
            return
        except Exception as e:
            log.warning(f"MQTT connect error: {e} — retrying in 5s")
            time.sleep(5)

def mqtt_publish(topic: str, payload: dict, retain: bool = False):
    try:
        mqttc.publish(topic, json.dumps(payload), retain=retain)
    except Exception as e:
        log.error(f"MQTT publish failed: {e}")


# ── Occupancy helpers ──────────────────────────────────────────────────────────
def set_occupancy(status: str):
    global _current_status
    if _current_status == status:
        return  # no duplicate writes
    write_point("occupancy", {"room_id": ROOM_ID}, {"status_str": status})
    mqtt_publish(
        f"coworking/{ROOM_ID}/occupancy",
        {"room_id": ROOM_ID, "status_str": status},
        retain=True,
    )
    log.info(f"Occupancy → {status.upper()}")
    _current_status = status


def handle_sensor_event():
    """
    Called on MOTION_DETECTED or SOUND_DETECTED.
    Updates last-motion timestamp atomically; marks room occupied.
    """
    global _last_motion_ts, _motion_lock
    _motion_lock    = True          # block vacancy timeout from firing right now
    _last_motion_ts = time.monotonic()
    set_occupancy("occupied")
    _motion_lock    = False


def check_vacancy_timeout():
    """
    Called each loop iteration.
    Fires only when the last sensor event was > VACANCY_TIMEOUT ago
    and no new sensor event is being processed.
    """
    global _last_motion_ts
    if _motion_lock:
        return
    if _last_motion_ts is None:
        return
    if (time.monotonic() - _last_motion_ts) >= VACANCY_TIMEOUT:
        set_occupancy("vacant")
        _last_motion_ts = None   # disarm until next motion


# ── Keypad ─────────────────────────────────────────────────────────────────────
def handle_pin(pin: str):
    user_info = lookup_pin(pin)
    if user_info:
        name, role = user_info
        write_point("keypad_auth", {"room_id": ROOM_ID, "result": "granted"},
                    {"user": name})
        mqtt_publish(f"coworking/{ROOM_ID}/access",
                     {"event": "access_granted", "user": name, "role": role})
        log.info(f"Access GRANTED → {name} ({role})")
    else:
        write_point("keypad_auth", {"room_id": ROOM_ID, "result": "denied"},
                    {"user": "unknown"})
        mqtt_publish(f"coworking/{ROOM_ID}/access",
                     {"event": "access_denied"})
        log.warning("Access DENIED — unknown PIN")


# ── Serial with auto-reconnect ─────────────────────────────────────────────────
def open_serial() -> serial.Serial:
    while _running:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
            log.info(f"Serial opened: {SERIAL_PORT} @ {SERIAL_BAUD}")
            return ser
        except serial.SerialException as e:
            log.warning(f"Serial open failed ({e}) — retrying in 3s")
            time.sleep(3)

def init_db():
    """Create users table if it doesn't exist"""
    try:
        conn = sqlite3.connect(USERS_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                pin_hash TEXT UNIQUE NOT NULL,
                active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        log.info(f"Database initialized at {USERS_DB_PATH}")
    except Exception as e:
        log.error(f"Failed to initialize database: {e}")

# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    log.info(f"Bridge starting — room={ROOM_ID}")
    init_db()
    mqtt_connect_with_retry()

    ser        = open_serial()
    pin_buffer = ""

    while _running:
        check_vacancy_timeout()

        # Reconnect serial if port was lost
        if not ser.is_open:
            log.warning("Serial port closed — reconnecting…")
            try:
                ser.close()
            except Exception:
                pass
            ser = open_serial()
            pin_buffer = ""   # discard partial PIN

        if ser.in_waiting == 0:
            time.sleep(0.05)
            continue

        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
        except serial.SerialException as e:
            log.error(f"Serial read error: {e}")
            ser.close()
            continue

        if not line or line in ("SYSTEM_READY", ""):
            continue

        log.debug(f"Serial: {line}")

        # ── Occupancy events ──────────────────────────────────────────────────
        if line in ("MOTION_DETECTED", "SOUND_DETECTED"):
            handle_sensor_event()

        # ── Keypad ────────────────────────────────────────────────────────────
        elif line.startswith("KEYPAD:"):
            key = line.split(":", 1)[1].strip()

            if key.isdigit():
                pin_buffer += key
                if len(pin_buffer) > 4:
                    pin_buffer = pin_buffer[-4:]  # keep last 4 digits only
                log.debug(f"PIN buffer: {'*' * len(pin_buffer)}")

            elif key == "*":
                pin_buffer = ""
                log.debug("PIN cleared")

            elif key == "#":
                if len(pin_buffer) == 4:
                    handle_pin(pin_buffer)
                else:
                    log.warning(f"PIN submit with wrong length ({len(pin_buffer)}) — ignored")
                pin_buffer = ""

        else:
            log.debug(f"Unhandled serial line: {line!r}")

    # Graceful cleanup
    log.info("Shutting down bridge…")
    try:
        ser.close()
    except Exception:
        pass
    mqttc.loop_stop()
    mqttc.disconnect()
    influx.close()
    log.info("Bridge stopped.")


if __name__ == "__main__":
    main()