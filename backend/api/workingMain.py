from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import os, jwt
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── InfluxDB configuration (same as bridge) ─────────────────────────────────
INFLUX_URL    = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN", "my-super-secret-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG", "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = influx_client.query_api()

# ── JWT Auth (unchanged) ────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "change-this")
security   = HTTPBearer()

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
    if req.username == "admin" and req.password == "admin":
        token = jwt.encode(
            {"sub": req.username, "exp": datetime.utcnow() + timedelta(hours=24)},
            JWT_SECRET, algorithm="HS256"
        )
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Bad credentials")

# ── Status endpoint (latest occupancy from Influx) ──────────────────────────
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

# ── Access alerts (denied keypad attempts) ─────────────────────────────────
@app.get("/keypad/alerts")
def get_alerts(room_id: str = "room1", hours: int = 24,
               user: str = Depends(verify_token)):
    start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    flux_query = f'''
        from(bucket: "{INFLUX_BUCKET}")
            |> range(start: {start_time})
            |> filter(fn: (r) => r._measurement == "keypad_auth" 
                and r.room_id == "{room_id}" 
                and r.result == "denied")
            |> filter(fn: (r) => r._field == "user")
            |> sort(columns: ["_time"], desc: true)
            |> limit(n: 50)
    '''
    try:
        tables = query_api.query(flux_query)
        alerts = []
        for table in tables:
            for record in table.records:
                alerts.append({
                    "time": record.get_time().isoformat(),
                    "result": "denied",
                    "user": record.get_value()
                })
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"InfluxDB query failed: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok"}