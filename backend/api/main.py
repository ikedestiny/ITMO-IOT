"""
COWORK · Smart Room Intelligence — FastAPI Backend
Fixes applied:
  - JWT auth now validates against SQLite users DB (PIN = password)
  - All endpoints consistently protected
  - Booking overlap query covers all 4 overlap cases + ownership check
  - daily_stats uses a single InfluxDB union query
  - /occupancy/history now requires auth
  - Proper error handling and structured responses throughout
"""

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import os, jwt, sqlite3, hashlib, secrets

app = FastAPI(title="COWORK API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config ─────────────────────────────────────────────────────────────────────
INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "my-super-secret-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")

USERS_DB_PATH    = os.getenv("USERS_DB_PATH",    "users.db")
BOOKINGS_DB_PATH = os.getenv("BOOKINGS_DB_PATH", "bookings.db")

JWT_SECRET       = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", 24))

# ── InfluxDB (lazy init so the app starts without it) ──────────────────────────
_influx_client = None
_query_api     = None

def get_influx():
    global _influx_client, _query_api
    if _influx_client is None:
        from influxdb_client import InfluxDBClient
        _influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        _query_api     = _influx_client.query_api()
    return _query_api


# ── Database helpers ───────────────────────────────────────────────────────────
def users_conn():
    c = sqlite3.connect(USERS_DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def bookings_conn():
    c = sqlite3.connect(BOOKINGS_DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def init_db():
    # 1. Initialize Users Database
    with users_conn() as db_users:
        cols = {row[1] for row in db_users.execute("PRAGMA table_info(users)")}

        # Always ensure base schema exists
        db_users.execute("""
            CREATE TABLE IF NOT EXISTS users (
                pin_hash   TEXT,
                pin        TEXT,
                name       TEXT NOT NULL,
                role       TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Add missing columns safely
        if "pin_hash" not in cols:
            db_users.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")

        if "pin" not in cols:
            db_users.execute("ALTER TABLE users ADD COLUMN pin TEXT")

        if "created_at" not in cols:
            db_users.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT (datetime('now'))")

        # Backfill pin_hash if needed
        rows = db_users.execute("SELECT pin FROM users WHERE pin_hash IS NULL").fetchall()
        for (pin,) in rows:
            if pin:
                db_users.execute(
                    "UPDATE users SET pin_hash = ? WHERE pin = ?",
                    (hash_pin(pin), pin)
                )

        db_users.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_pin_hash ON users(pin_hash)")
    # 2. Initialize Bookings Database
    with bookings_conn() as db_bookings:
        db_bookings.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id     TEXT NOT NULL,
                user_name   TEXT NOT NULL,
                owner_pin   TEXT NOT NULL DEFAULT '',
                start_time  TEXT NOT NULL,
                end_time    TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        
        # Migration: check columns against bookings
        cols_bookings = {row[1] for row in db_bookings.execute("PRAGMA table_info(bookings)")}
        if "owner_pin" not in cols_bookings:
            db_bookings.execute("ALTER TABLE bookings ADD COLUMN owner_pin TEXT NOT NULL DEFAULT ''")


@app.on_event("startup")
def startup():
    init_db()


# ── JWT ────────────────────────────────────────────────────────────────────────
security = HTTPBearer()

def make_token(pin: str, name: str, role: str) -> str:
    payload = {
        "sub":  pin,
        "name": name,
        "role": role,
        "exp":  datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_admin(payload: dict = Depends(decode_token)) -> dict:
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


# ── Auth endpoints ─────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    pin: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    name: str
    role: str

@app.post("/auth/token", response_model=LoginResponse)
def login(req: LoginRequest):
    """
    Login with a PIN. The PIN is looked up in the users DB.
    Returns a JWT containing the user's name and role.
    """
    h = hash_pin(req.pin)
    with users_conn() as db:
        row = db.execute(
            "SELECT pin, name, role FROM users WHERE pin_hash = ?", (h,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    token = make_token(row["pin"], row["name"], row["role"])
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        name=row["name"],
        role=row["role"],
    )

@app.get("/auth/me")
def me(payload: dict = Depends(decode_token)):
    return {"pin": payload["sub"], "name": payload["name"], "role": payload["role"]}


# ── Occupancy ──────────────────────────────────────────────────────────────────
@app.get("/status")
def get_status(room_id: str = "room1"):
    """Public endpoint — dashboard can poll without auth."""
    flux = f"""
        from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -2h)
            |> filter(fn: (r) => r._measurement == "occupancy" and r.room_id == "{room_id}")
            |> filter(fn: (r) => r._field == "status_str")
            |> last()
    """
    try:
        tables = get_influx().query(flux)
        if not tables or not tables[0].records:
            return {"room_id": room_id, "status": "unknown", "timestamp": None}
        rec = tables[0].records[0]
        return {
            "room_id":   room_id,
            "status":    rec.get_value(),
            "timestamp": rec.get_time().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"InfluxDB unavailable: {e}")


@app.get("/occupancy/history")
def occupancy_history(
    room_id: str = "room1",
    hours: int = Query(default=8, ge=1, le=168),
    payload: dict = Depends(decode_token),
):
    """History requires auth — protected from public scraping."""
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    flux = f"""
        from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "occupancy" and r.room_id == "{room_id}")
            |> filter(fn: (r) => r._field == "status_str")
            |> sort(columns: ["_time"])
    """
    try:
        tables = get_influx().query(flux)
        return [
            {"time": rec.get_time().isoformat(), "status": rec.get_value()}
            for table in tables for rec in table.records
        ]
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Access log ─────────────────────────────────────────────────────────────────
@app.get("/access/log")
def access_log(
    room_id: str = "room1",
    hours: int = Query(default=24, ge=1, le=720),
    result: str = Query(default="all", pattern="^(all|granted|denied)$"),
    payload: dict = Depends(decode_token),
):
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result_filter = (
        f'r.result == "{result}"'
        if result != "all"
        else "true"
    )
    flux = f"""
        from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "keypad_auth"
                               and r.room_id == "{room_id}"
                               and {result_filter})
            |> filter(fn: (r) => r._field == "user")
            |> sort(columns: ["_time"], desc: true)
            |> limit(n: 200)
    """
    try:
        tables = get_influx().query(flux)
        return [
            {
                "time":   rec.get_time().isoformat(),
                "result": rec.values.get("result"),
                "user":   rec.get_value(),
            }
            for table in tables for rec in table.records
        ]
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# Backward-compat alias
@app.get("/keypad/alerts")
def get_alerts(room_id: str = "room1", hours: int = 24, payload: dict = Depends(decode_token)):
    return access_log(room_id=room_id, hours=hours, result="denied", payload=payload)


# ── Statistics ─────────────────────────────────────────────────────────────────
@app.get("/stats/daily")
def daily_stats(
    room_id: str = "room1",
    days: int = Query(default=7, ge=1, le=30),
    payload: dict = Depends(decode_token),
):
    """
    Returns per-day granted/denied counts.
    Uses a single Flux query with union + pivot for atomicity.
    """
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    flux = f"""
        denied = from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start})
            |> filter(fn:(r) => r._measurement == "keypad_auth"
                             and r.room_id == "{room_id}"
                             and r.result == "denied"
                             and r._field == "user")
            |> aggregateWindow(every: 1d, fn: count, createEmpty: true)
            |> map(fn:(r) => ({{r with kind: "denied"}}))

        granted = from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start})
            |> filter(fn:(r) => r._measurement == "keypad_auth"
                             and r.room_id == "{room_id}"
                             and r.result == "granted"
                             and r._field == "user")
            |> aggregateWindow(every: 1d, fn: count, createEmpty: true)
            |> map(fn:(r) => ({{r with kind: "granted"}}))

        union(tables: [denied, granted])
            |> yield(name: "stats")
    """
    try:
        tables = get_influx().query(flux)
        denied  = []
        granted = []
        for table in tables:
            for rec in table.records:
                entry = {"time": rec.get_time().isoformat(), "count": rec.get_value() or 0}
                if rec.values.get("kind") == "denied":
                    denied.append(entry)
                else:
                    granted.append(entry)
        return {"denied": denied, "granted": granted}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── User management ────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    pin:  str
    name: str
    role: str = "user"

    @field_validator("pin")
    @classmethod
    def pin_must_be_4_digits(cls, v):
        if not v.isdigit() or len(v) != 4:
            raise ValueError("PIN must be exactly 4 digits")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v):
        if v not in ("user", "admin"):
            raise ValueError("role must be 'user' or 'admin'")
        return v


@app.post("/users", status_code=201)
def add_user(user: UserCreate, admin: dict = Depends(require_admin)):
    h = hash_pin(user.pin)
    with users_conn() as db:
        try:
            db.execute(
                "INSERT INTO users (pin_hash, pin, name, role) VALUES (?,?,?,?)",
                (h, user.pin, user.name, user.role),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="PIN already registered")
    return {"pin": user.pin, "name": user.name, "role": user.role}


@app.get("/users")
def list_users(admin: dict = Depends(require_admin)):
    with users_conn() as db:
        rows = db.execute(
            "SELECT pin, name, role, created_at FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/users/{pin}", status_code=200)
def delete_user(pin: str, admin: dict = Depends(require_admin)):
    if pin == admin["sub"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    with users_conn() as db:
        db.execute("DELETE FROM users WHERE pin = ?", (pin,))
        if db.total_changes == 0:
            raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": pin}


# ── Bookings ───────────────────────────────────────────────────────────────────
class BookingCreate(BaseModel):
    room_id:    str
    user_name:  str
    start_time: str
    end_time:   str

    @field_validator("start_time", "end_time")
    @classmethod
    def must_be_iso(cls, v):
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Must be ISO 8601 datetime")
        return v

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, v, info):
        if "start_time" in info.data:
            s = datetime.fromisoformat(info.data["start_time"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if e <= s:
                raise ValueError("end_time must be after start_time")
        return v


def _check_overlap(db, room_id: str, start: str, end: str, exclude_id: int = None):
    """
    True overlap: two intervals [s1,e1) and [s2,e2) overlap iff s1 < e2 AND s2 < e1.
    Covers all four cases: partial left/right, containment, identity.
    """
    q = """
        SELECT id FROM bookings
        WHERE room_id = ?
          AND start_time < ?
          AND end_time   > ?
    """
    params = [room_id, end, start]
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(exclude_id)
    return db.execute(q, params).fetchone() is not None


@app.post("/bookings", status_code=201)
def create_booking(booking: BookingCreate, payload: dict = Depends(decode_token)):
    with bookings_conn() as db:
        if _check_overlap(db, booking.room_id, booking.start_time, booking.end_time):
            raise HTTPException(status_code=409, detail="Time slot conflicts with an existing booking")
        cur = db.execute(
            "INSERT INTO bookings (room_id, user_name, owner_pin, start_time, end_time) VALUES (?,?,?,?,?)",
            (booking.room_id, booking.user_name, payload["sub"], booking.start_time, booking.end_time),
        )
        new_id = cur.lastrowid
    return {
        "id": new_id,
        **booking.model_dump(),
        "owner_pin":  payload["sub"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/bookings")
def get_bookings(
    room_id: Optional[str] = None,
    date:    Optional[str] = None,
    payload: dict = Depends(decode_token),
):
    q      = "SELECT * FROM bookings"
    params = []
    conds  = []
    if room_id:
        conds.append("room_id = ?");  params.append(room_id)
    if date:
        conds.append("date(start_time) = ?"); params.append(date)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY start_time"
    with bookings_conn() as db:
        rows = db.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@app.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int, payload: dict = Depends(decode_token)):
    with bookings_conn() as db:
        row = db.execute("SELECT owner_pin FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Booking not found")
        # Only the owner or an admin can cancel
        if row["owner_pin"] != payload["sub"] and payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Not your booking")
        db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    return {"deleted": booking_id}


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Static (must be last) ──────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")