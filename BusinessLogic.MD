## Business Logic of the Coworking Space System

The system implements the following business rules and processes:

### 1. Occupancy Management

- **Motion and sound detection** – When the PIR sensor detects motion or the sound sensor detects noise above threshold, the occupancy status becomes `occupied`.
- **Vacancy timeout** – If no motion or sound is detected for a configurable period (default 30 seconds), the occupancy status automatically changes to `vacant`.
- **Status persistence** – Occupancy changes are recorded in InfluxDB with timestamps and also published via MQTT (retained message).
- **Duplicate prevention** – The bridge only writes a new occupancy state if it differs from the current state, avoiding unnecessary database writes.

### 2. Keypad Access Control

- **PIN authentication** – Users must enter a 4‑digit PIN followed by `#`. The system validates against an authorised list (initially hardcoded, later via database).
- **Access decision** – If PIN is valid → `granted`; if invalid → `denied`.
- **Audit logging** – Every keypad attempt (granted or denied) is written to InfluxDB with tags: `room_id`, `result`, and field `user` (name if granted, `unknown` if denied).
- **MQTT notification** – Real‑time access events are published to `coworking/{room_id}/access` for integrations (e.g., door lock, Telegram bot).
- **PIN buffer** – The system accumulates digits until `#` is pressed; `*` clears the buffer. Invalid length (not 4 digits) is ignored.

### 3. User Management (Admin)

- **User list** – Authorised users are stored in a SQLite database (`users` table). Each user has `pin`, `name`, `role` (admin/user), and creation timestamp.
- **Default admin** – A hardcoded admin user with PIN `0000` and name `Admin` is created automatically.
- **Add user** – Admin can add a new user by providing a PIN and name. PIN must be 4 digits and unique.
- **Delete user** – Admin can remove a user by PIN.
- **Role‑based access** – The system reserves `role` for future expansion (e.g., admin vs regular user), but currently all authenticated API users have full access (token issued via `admin`/`admin`).

### 4. Booking System

- **Create booking** – Authenticated users can reserve a room by providing: `room_id`, `user_name`, `start_time`, `end_time`. All fields are required.
- **Overlap prevention** – The system checks for existing bookings that overlap with the requested time slot. If overlap exists, booking is rejected with `409 Conflict`.
- **Booking storage** – Bookings are stored in a separate SQLite database (`bookings` table) with auto‑increment `id`.
- **List bookings** – Users can view all bookings, filter by `room_id` or specific date (YYYY-MM-DD).
- **Cancel booking** – Any authenticated user can delete a booking by its `id`. (No ownership check – can be extended.)

### 5. API Security & Access

- **Public endpoints** – `/status` (occupancy) and `/health` are open without authentication.
- **Protected endpoints** – All other endpoints (access log, users, bookings, statistics, history) require a valid JWT token.
- **Token issuance** – Only `admin`/`admin` credentials are accepted (hardcoded for demo). Token expires after 24 hours.
- **Token validation** – Every protected request verifies the JWT signature and expiration. Invalid/expired tokens return `401 Unauthorized`.

### 6. Data Retention & Statistics

- **Access log retention** – The API queries the last 24 hours by default, but the frontend allows up to 48 hours (configurable via `hours` parameter). InfluxDB retains all data indefinitely unless a retention policy is set.
- **Daily statistics** – The system counts granted and denied keypad attempts per day over a configurable number of days (default 7). It uses InfluxDB’s `aggregateWindow` function.
- **Occupancy history** – The frontend displays the last 8 hours of occupancy changes; the API can return any time range.

### 7. Real‑time Behaviour

- **Polling** – The frontend polls `/status` every 4 seconds and protected endpoints every 15–60 seconds. No WebSocket or MQTT over WebSocket is implemented yet.
- **MQTT (internal)** – The bridge publishes occupancy changes and access events to MQTT, but the API does not consume them. This allows external subscribers (e.g., a Telegram bot) to react in real time.

### 8. Error Handling & Resilience

- **Serial read errors** – The bridge catches `SerialException` and retries after a short delay, preventing crash on transient serial issues.
- **InfluxDB write failures** – The bridge prints errors but continues running; no retry logic (could be improved).
- **API error responses** – All endpoints return appropriate HTTP status codes (400, 401, 404, 409, 500) with descriptive JSON error messages.
- **Frontend token expiry** – On receiving `401`, the frontend automatically logs out, clears local storage, and prompts for re‑authentication.

### 9. Hardware‑Specific Logic

- **PIR warm‑up** – The microcontroller waits 30 seconds after boot before declaring `SYSTEM_READY` to stabilise the PIR sensor.
- **Cooldown** – The microcontroller enforces a 3‑second cooldown between sensor readings to avoid flooding the serial line.
- **Sensor interpretation** – PIR output `HIGH` means motion detected; sound module output `LOW` means sound detected (active low). The bridge maps these to `MOTION_DETECTED` and `SOUND_DETECTED` strings.

### 10. Deployment & Environment Logic

- **Configuration via environment variables** – All critical parameters (serial port, room ID, vacancy timeout, MQTT/InfluxDB credentials, database paths, JWT secret) are read from environment variables, allowing easy reconfiguration without code changes.
- **Dockerised backend** – All services except the bridge run in containers, with volumes for persistent data.
- **SELinux compatibility** – The `:z` flag is used on volume mounts for Fedora hosts.

---

This list defines **how the system behaves from a business perspective** – the rules that govern occupancy, access, bookings, and data flow.