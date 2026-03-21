from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import jwt
import os
import json
import asyncio
import aiomqtt
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

app = FastAPI(title="Coworking API", version="1.0.0")
security = HTTPBearer()

# ─── Config ───────────────────────────────────────────────────────────────────
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER   = os.getenv("MQTT_USER", "server")
MQTT_PASS   = os.getenv("MQTT_PASS", "serverpass")
INFLUX_URL  = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "my-super-secret-token")
INFLUX_ORG  = os.getenv("INFLUX_ORG", "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")
JWT_SECRET  = os.getenv("JWT_SECRET", "change-this-secret")

# ─── InfluxDB client ─────────────────────────────────────────────────────────
influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api: QueryApi = influx.query_api()

# ─── In-memory bookings store (replace with PostgreSQL in production) ─────────
bookings: List[dict] = []

# ─── Models ───────────────────────────────────────────────────────────────────
class BookingCreate(BaseModel):
    room_id: str
    user_name: str
    start_time: datetime
    end_time: datetime
    description: Optional[str] = ""

class TokenRequest(BaseModel):
    username: str
    password: str

# ─── Auth ─────────────────────────────────────────────────────────────────────
def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/auth/token")
def get_token(req: TokenRequest):
    # Simple demo auth — replace with real user DB
    if req.username == "admin" and req.password == "admin":
        return {"access_token": create_token(req.username), "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/status")
def get_status(room_id: str = "room1"):
    """Get current occupancy status from InfluxDB (latest value)."""
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -5m)
      |> filter(fn: (r) => r._measurement == "occupancy" and r.room_id == "{room_id}")
      |> filter(fn: (r) => r._field == "status_str")
      |> last()
    '''
    try:
        tables = query_api.query(query)
        for table in tables:
            for record in table.records:
                return {
                    "room_id": room_id,
                    "status": record.get_value(),
                    "timestamp": record.get_time().isoformat()
                }
    except Exception as e:
        pass  # Fall through to unknown
    return {"room_id": room_id, "status": "unknown", "timestamp": datetime.utcnow().isoformat()}


@app.get("/bookings")
def get_bookings(room_id: str = "room1", date: Optional[str] = None):
    """List bookings for a room, optionally filtered by date (YYYY-MM-DD)."""
    result = [b for b in bookings if b["room_id"] == room_id]
    if date:
        result = [b for b in result if b["start_time"].startswith(date)]
    return result


@app.post("/booking", status_code=201)
async def create_booking(booking: BookingCreate, user: str = Depends(verify_token)):
    """Create a booking and push sync to device via MQTT."""
    # Check for conflicts
    for b in bookings:
        if b["room_id"] == booking.room_id:
            b_start = datetime.fromisoformat(b["start_time"])
            b_end   = datetime.fromisoformat(b["end_time"])
            if not (booking.end_time <= b_start or booking.start_time >= b_end):
                raise HTTPException(status_code=409, detail="Time slot already booked")

    new_booking = {
        "id": len(bookings) + 1,
        "room_id": booking.room_id,
        "user_name": booking.user_name,
        "start_time": booking.start_time.isoformat(),
        "end_time": booking.end_time.isoformat(),
        "description": booking.description,
        "created_by": user
    }
    bookings.append(new_booking)

    # Push active booking status to device
    now = datetime.utcnow()
    is_active = booking.start_time <= now <= booking.end_time
    sync_payload = json.dumps({
        "active": is_active,
        "until": booking.end_time.strftime("%H:%M"),
        "user": booking.user_name
    })

    try:
        async with aiomqtt.Client(
            hostname=MQTT_BROKER, port=MQTT_PORT,
            username=MQTT_USER, password=MQTT_PASS
        ) as mqtt:
            topic = f"coworking/{booking.room_id}/booking/sync"
            await mqtt.publish(topic, sync_payload, qos=1, retain=True)
    except Exception as e:
        print(f"[MQTT] Failed to sync booking: {e}")

    return new_booking


@app.delete("/booking/{booking_id}")
async def delete_booking(booking_id: int, user: str = Depends(verify_token)):
    global bookings
    before = len(bookings)
    bookings = [b for b in bookings if b["id"] != booking_id]
    if len(bookings) == before:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"deleted": booking_id}


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
