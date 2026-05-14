from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import os, jwt, sqlite3
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ========================
# InfluxDB configuration
# ========================
INFLUX_URL    = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN", "my-super-secret-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG", "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = influx_client.query_api()

# ========================
# SQLite databases
# ========================
USERS_DB_PATH = os.getenv("USERS_DB_PATH", "users.db")
BOOKINGS_DB_PATH = os.getenv("BOOKINGS_DB_PATH", "bookings.db")

def init_users_db():
    conn = sqlite3.connect(USERS_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            pin TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    # Insert default admin user (optional)
    conn.execute("INSERT OR IGNORE INTO users (pin, name, role) VALUES ('0000', 'Admin', 'admin')")
    conn.commit()
    conn.close()

def init_bookings_db():
    conn = sqlite3.connect(BOOKINGS_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            user_name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_users_db()
    init_bookings_db()

# ========================
# Helper functions
# ========================
def get_user_db():
    return sqlite3.connect(USERS_DB_PATH)

def get_bookings_db():
    return sqlite3.connect(BOOKINGS_DB_PATH)

# ========================
# JWT Auth (unchanged)
# ========================
JWT_SECRET = os.getenv("JWT_SECRET", "change-this")
security = HTTPBearer()

class TokenRequest(BaseModel):
    username: str
    password: str

def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/auth/token")
def get_token(req: TokenRequest):
    # For demo, accept admin/admin
    if req.username == "admin" and req.password == "admin":
        token = jwt.encode(
            {"sub": req.username, "exp": datetime.utcnow() + timedelta(hours=24)},
            JWT_SECRET, algorithm="HS256"
        )
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Bad credentials")

# ========================
# 1. Occupancy endpoints
# ========================
@app.get("/status")
def get_status(room_id: str = "room1"):
    flux_query = f'''
        from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -1h)
            |> filter(fn: (r) => r._measurement == "occupancy" and r.room_id == "{room_id}")
            |> filter(fn: (r) => r._field == "status_str")
            |> last()
    '''
    try:
        tables = query_api.query(flux_query)
        if not tables:
            return {"room_id": room_id, "status": "unknown", "timestamp": None}
        record = tables[0].records[0]
        return {
            "room_id": room_id,
            "status": record.get_value(),
            "timestamp": record.get_time().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"InfluxDB query failed: {str(e)}")

@app.get("/occupancy/history")
def occupancy_history(room_id: str = "room1", start: Optional[str] = None, end: Optional[str] = None):
    start_time = start or (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    end_time = end or datetime.utcnow().isoformat() + "Z"
    flux = f'''
        from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start_time}, stop: {end_time})
            |> filter(fn: (r) => r._measurement == "occupancy" and r.room_id == "{room_id}")
            |> filter(fn: (r) => r._field == "status_str")
            |> sort(columns: ["_time"])
    '''
    try:
        tables = query_api.query(flux)
        history = []
        for table in tables:
            for record in table.records:
                history.append({
                    "time": record.get_time().isoformat(),
                    "status": record.get_value()
                })
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========================
# 2. Access log (full)
# ========================
@app.get("/access/log")
def access_log(room_id: str = "room1", hours: int = 24, result: str = "all", user: str = Depends(verify_token)):
    start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    result_filter = f'r.result == "{result}"' if result != "all" else "r.result =~ /.*/"
    flux = f'''
        from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start_time})
            |> filter(fn: (r) => r._measurement == "keypad_auth" and r.room_id == "{room_id}" and {result_filter})
            |> filter(fn: (r) => r._field == "user")
            |> sort(columns: ["_time"], desc: true)
            |> limit(n: 100)
    '''
    try:
        tables = query_api.query(flux)
        entries = []
        for table in tables:
            for record in table.records:
                entries.append({
                    "time": record.get_time().isoformat(),
                    "result": record.values.get("result"),
                    "user": record.get_value()
                })
        return entries
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Backward compatibility
@app.get("/keypad/alerts")
def get_alerts(room_id: str = "room1", hours: int = 24, user: str = Depends(verify_token)):
    return access_log(room_id, hours, result="denied", user=user)

# ========================
# 3. Daily statistics
# ========================
@app.get("/stats/daily")
def daily_stats(room_id: str = "room1", days: int = 7, user: str = Depends(verify_token)):
    start = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    # Count of denied attempts per day
    flux_denied = f'''
        from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "keypad_auth" and r.room_id == "{room_id}" and r.result == "denied")
            |> filter(fn: (r) => r._field == "user")
            |> aggregateWindow(every: 1d, fn: count)
            |> yield(name: "denied")
    '''
    # Count of granted attempts per day
    flux_granted = f'''
        from(bucket:"{INFLUX_BUCKET}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "keypad_auth" and r.room_id == "{room_id}" and r.result == "granted")
            |> filter(fn: (r) => r._field == "user")
            |> aggregateWindow(every: 1d, fn: count)
            |> yield(name: "granted")
    '''
    try:
        denied_tables = query_api.query(flux_denied)
        granted_tables = query_api.query(flux_granted)
        # Build result per day (simple)
        stats = []
        # Combine both results (simplified: just return raw counts)
        # Better to process into a dict keyed by date
        return {"denied": [{"time": r.get_time().isoformat(), "count": r.get_value()} for t in denied_tables for r in t.records],
                "granted": [{"time": r.get_time().isoformat(), "count": r.get_value()} for t in granted_tables for r in t.records]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========================
# 4. User management
# ========================
class UserCreate(BaseModel):
    pin: str
    name: str
    role: Optional[str] = "user"

@app.post("/users")
def add_user(user: UserCreate, admin: str = Depends(verify_token)):
    db = get_user_db()
    try:
        db.execute("INSERT INTO users (pin, name, role) VALUES (?, ?, ?)",
                   (user.pin, user.name, user.role))
        db.commit()
        return {"pin": user.pin, "name": user.name, "role": user.role}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="User with this PIN already exists")
    finally:
        db.close()

@app.get("/users")
def list_users(admin: str = Depends(verify_token)):
    db = get_user_db()
    users = db.execute("SELECT pin, name, role, created_at FROM users ORDER BY created_at").fetchall()
    db.close()
    return [{"pin": u[0], "name": u[1], "role": u[2], "created_at": u[3]} for u in users]

@app.delete("/users/{pin}")
def delete_user(pin: str, admin: str = Depends(verify_token)):
    db = get_user_db()
    db.execute("DELETE FROM users WHERE pin = ?", (pin,))
    db.commit()
    if db.total_changes == 0:
        raise HTTPException(status_code=404, detail="User not found")
    db.close()
    return {"deleted": pin}

# ========================
# 5. Bookings management
# ========================
class BookingCreate(BaseModel):
    room_id: str
    user_name: str
    start_time: str   # ISO format
    end_time: str

class BookingResponse(BaseModel):
    id: int
    room_id: str
    user_name: str
    start_time: str
    end_time: str
    created_at: str

@app.post("/bookings")
def create_booking(booking: BookingCreate, user: str = Depends(verify_token)):
    # Check for overlapping bookings
    db = get_bookings_db()
    overlap = db.execute("""
        SELECT id FROM bookings
        WHERE room_id = ? AND (
            (start_time <= ? AND end_time > ?) OR
            (start_time < ? AND end_time >= ?)
        )
    """, (booking.room_id, booking.end_time, booking.start_time, booking.end_time, booking.start_time)).fetchone()
    if overlap:
        db.close()
        raise HTTPException(status_code=409, detail="Time slot already booked")
    cur = db.execute("""
        INSERT INTO bookings (room_id, user_name, start_time, end_time)
        VALUES (?, ?, ?, ?)
    """, (booking.room_id, booking.user_name, booking.start_time, booking.end_time))
    db.commit()
    new_id = cur.lastrowid
    db.close()
    return {"id": new_id, **booking.dict(), "created_at": datetime.utcnow().isoformat()}

@app.get("/bookings")
def get_bookings(room_id: Optional[str] = None, date: Optional[str] = None, user: str = Depends(verify_token)):
    db = get_bookings_db()
    query = "SELECT id, room_id, user_name, start_time, end_time, created_at FROM bookings"
    params = []
    conditions = []
    if room_id:
        conditions.append("room_id = ?")
        params.append(room_id)
    if date:
        # bookings that occur on the given date (YYYY-MM-DD)
        conditions.append("date(start_time) = ?")
        params.append(date)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY start_time"
    rows = db.execute(query, params).fetchall()
    db.close()
    return [BookingResponse(id=r[0], room_id=r[1], user_name=r[2], start_time=r[3], end_time=r[4], created_at=r[5]) for r in rows]

@app.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int, user: str = Depends(verify_token)):
    db = get_bookings_db()
    db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    db.commit()
    if db.total_changes == 0:
        db.close()
        raise HTTPException(status_code=404, detail="Booking not found")
    db.close()
    return {"deleted": booking_id}

# ========================
# Health
# ========================
@app.get("/health")
def health():
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
