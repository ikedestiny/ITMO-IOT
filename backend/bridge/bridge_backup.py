import os, json, time, serial
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
SERIAL_PORT      = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
ROOM_ID          = os.getenv("ROOM_ID", "room1")
VACANCY_TIMEOUT  = int(os.getenv("VACANCY_TIMEOUT", 30))

MQTT_BROKER  = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT    = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER    = os.getenv("MQTT_USER", "server")
MQTT_PASS    = os.getenv("MQTT_PASS", "serverpass")

INFLUX_URL    = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN", "my-super-secret-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG", "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")

AUTHORIZED_PINS = {
    "1234": "Alice (Manager)",
    "5678": "Bob (Developer)",
    "0000": "Admin",
}

# ── Clients ───────────────────────────────────────────────────────────────────
influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

mqttc = mqtt.Client()
mqttc.username_pw_set(MQTT_USER, MQTT_PASS)
mqttc.connect(MQTT_BROKER, MQTT_PORT)
mqttc.loop_start()

# ── Helpers ───────────────────────────────────────────────────────────────────
def now():
    return datetime.now(timezone.utc)

def write_point(measurement: str, tags: dict, fields: dict):
    p = Point(measurement).time(now(), WritePrecision.NS)
    for k, v in tags.items():   p = p.tag(k, v)
    for k, v in fields.items(): p = p.field(k, v)
    write_api.write(bucket=INFLUX_BUCKET, record=p)

def set_occupancy(status: str):
    """Write to InfluxDB + publish retained MQTT state."""
    write_point("occupancy", {"room_id": ROOM_ID}, {"status_str": status})
    mqttc.publish(
        f"coworking/{ROOM_ID}/occupancy",
        json.dumps({"room_id": ROOM_ID, "status_str": status}),
        retain=True
    )
    print(f"[{now().strftime('%H:%M:%S')}] Occupancy → {status.upper()}")

def handle_pin(pin: str):
    if pin in AUTHORIZED_PINS:
        user = AUTHORIZED_PINS[pin]
        write_point("keypad_auth", {"room_id": ROOM_ID, "result": "granted"}, {"user": user})
        mqttc.publish(f"coworking/{ROOM_ID}/access",
                      json.dumps({"event": "access_granted", "user": user}))
        print(f"[{now().strftime('%H:%M:%S')}] Access GRANTED → {user}")
    else:
        write_point("keypad_auth", {"room_id": ROOM_ID, "result": "denied"}, {"user": "unknown"})
        mqttc.publish(f"coworking/{ROOM_ID}/access",
                      json.dumps({"event": "access_denied"}))
        print(f"[{now().strftime('%H:%M:%S')}] Access DENIED")

# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    ser = serial.Serial(SERIAL_PORT, 115200, timeout=1)
    print(f"[Bridge] Started — room={ROOM_ID}, port={SERIAL_PORT}")

    pin_buffer      = ""
    last_motion     = None   # timestamp of last sensor trigger
    current_status  = None   # track state to avoid duplicate writes

    while True:
        # Vacancy timeout — check every iteration regardless of serial
        if last_motion and (time.time() - last_motion > VACANCY_TIMEOUT):
            if current_status != "vacant":
                set_occupancy("vacant")
                current_status = "vacant"
            last_motion = None

        if ser.in_waiting == 0:
            time.sleep(0.05)
            continue

        try:
            line = ser.readline().decode("utf-8").strip()
        except UnicodeDecodeError:
            continue

        if not line or line == "SYSTEM_READY":
            continue

        # ── Occupancy events ──────────────────────────────────────
        if line in ("MOTION_DETECTED", "SOUND_DETECTED"):
            last_motion = time.time()
            if current_status != "occupied":
                set_occupancy("occupied")
                current_status = "occupied"

        # ── Keypad input ──────────────────────────────────────────
        elif line.startswith("KEYPAD:"):
            key = line.split(":")[1].strip()

            if key.isdigit():
                pin_buffer += key
                print(f"[PIN] {'*' * len(pin_buffer)}")

            elif key == '*':
                pin_buffer = ""
                print("[PIN] Cleared")

            elif key == '#':
                if len(pin_buffer) == 4:
                    handle_pin(pin_buffer)
                else:
                    print(f"[PIN] Wrong length ({len(pin_buffer)} digits), ignored")
                pin_buffer = ""

        else:
            print(f"[Serial] Unhandled: {line}")

if __name__ == "__main__":
    main()