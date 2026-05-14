## Summary of Everything We Have Built

We created a **complete coworking space intelligence system** that monitors room occupancy, logs keypad access, and provides a web dashboard for administration. The system consists of hardware sensors, a bridge service, a time‑series database, a REST API, and a single‑page frontend – all containerised except the bridge.

### 1. Hardware & Microcontroller

- **ESP8266/Arduino** connected to:
  - PIR motion sensor (D5)
  - Sound sensor (KY‑038 / LM393, D6)
  - 4×3 keypad via I2C (PCF8574, address 0x20)
- Firmware (Arduino code) reads sensors and keypad, sends lines over Serial (115200 baud):
  - `MOTION_DETECTED`, `SOUND_DETECTED`, `PIR: x | SOUND: y`
  - `KEYPAD:<key>` for each key press
- Boot time: 30‑second PIR warm‑up, then `SYSTEM_READY`.

### 2. Bridge (Python)

- **Runs on the host** (not containerised) because it needs direct access to `/dev/ttyUSB0`.
- Reads serial data, processes PINs (4‑digit codes), controls vacancy timeout (default 30 seconds).
- **Writes to InfluxDB** (measurements `occupancy` and `keypad_auth`) and **publishes to MQTT**.
- Authorised PINs hardcoded initially (`1234`, `5678`, `0000`).
- Environment variables for InfluxDB, MQTT, room ID, timeout.

### 3. Backend Stack (Docker Compose)

- **Mosquitto** – MQTT broker (port 1883), with authentication (`server`/`serverpass`).
- **InfluxDB 2.x** – time‑series database (port 8086) with initial organisation `coworking`, bucket `occupancy`, admin token `my-super-secret-token`.
- **Grafana** – connected to InfluxDB for dashboards (optional, port 3000).
- **FastAPI** – REST API service (port 8000) built from `../backend/api`.
- **Nginx** – reverse proxy (ports 80/443) to FastAPI and Grafana (not fully configured yet, but present).
- Volumes for persistence: InfluxDB data, Grafana data, Mosquitto data, SQLite database files for users and bookings.

### 4. FastAPI Features (Enhanced)

We extended the original API with:

- **Authentication** – JWT token endpoint `/auth/token` (hardcoded `admin`/`admin` for demo).
- **Occupancy** – `/status` (latest), `/occupancy/history` (time range).
- **Access log** – `/access/log` (filter by `result=all/granted/denied`), backward‑compatible `/keypad/alerts`.
- **Daily statistics** – `/stats/daily` (counts of denied/granted per day).
- **User management** – CRUD on SQLite (`/users`, POST/DELETE) – replaces hardcoded PINs.
- **Bookings** – `/bookings` (create, list, cancel) – stored in separate SQLite.
- **Health check** – `/health`.
- **Static file serving** – mounts `./static` to serve the frontend `index.html` at root.

### 5. SQLite Databases

- `users.db` – table `users(pin, name, role, created_at)`. Default admin user with PIN `0000`.
- `bookings.db` – table `bookings(id, room_id, user_name, start_time, end_time, created_at)`.
- Mounted as volumes in Docker (`./data/users.db:/app/users.db:z` etc.) and environment variables `USERS_DB_PATH`, `BOOKINGS_DB_PATH`.

### 6. Frontend (Single HTML File)

- **Pure HTML/CSS/JS** – no frameworks.
- **Dark theme** with tabs for:
  - Dashboard (live occupancy + history chart using Chart.js)
  - Access log (toggle all / denied only)
  - User management (list, add, delete users)
  - Bookings (create, list, cancel)
  - Statistics (bar chart of daily denied/granted)
- **Authentication** – token stored in `localStorage`, auto‑refresh on 401, logout button.
- **Polling** – occupancy every 4 seconds, access log every 15 seconds, stats every 60 seconds.
- **Served via FastAPI** at `http://localhost:8000` (static mount), not directly as `file://`.

### 7. Key Issues & Solutions

| Problem | Solution |
|---------|----------|
| Bridge missing Python packages | `pip install influxdb-client paho-mqtt pyserial` |
| Serial port busy (pio process) | Kill `pio` (PlatformIO monitor) |
| Bridge crashes on first read | Add `time.sleep(2)` after opening serial port (Arduino reset) |
| Sensors (PIR, sound) not working | Hardware troubleshooting: PIR constant HIGH (potentiometer/timeout) and sound sensitivity adjustment |
| FastAPI container cannot open SQLite files | Create `./data` directory, set environment variables `USERS_DB_PATH`, `BOOKINGS_DB_PATH`, add `:z` flag for SELinux |
| Frontend CORS errors when opened as `file://` | Serve via FastAPI static files, open `http://localhost:8000` |
| FastAPI returning empty `/keypad/alerts` | Verified InfluxDB has data; problem was API not rebuilt – rebuild fixed it |

### 8. Current State

- **Hardware** – keypad works fully (grant/deny logging). PIR and sound sensors need adjustment (always report motion / rarely detect sound). Occupancy changes correctly on keypad events but PIR keeps it occupied.
- **Bridge** – runs manually (we can set up as a systemd service later).
- **Docker stack** – all containers run, FastAPI serves frontend, InfluxDB stores data, Grafana available.
- **API** – all endpoints tested and return correct data.
- **Frontend** – fully functional after login, displays live occupancy, access log, user management, bookings, statistics.


---

**We have built a complete IoT coworking monitoring and management system from hardware to dashboard.** All components are integrated, and the frontend provides a polished user experience.