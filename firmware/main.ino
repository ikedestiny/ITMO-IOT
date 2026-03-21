// ─────────────────────────────────────────────────────────────────────────────
// Coworking Occupancy Monitor — main.ino
// Platform: NodeMCU v3 Lolin (ESP8266)
// Author:   Your Name
//
// Stages:
//   1. Sensors + LED + Display working individually  ← drivers.h
//   2. Sliding window occupancy logic                ← occupancy.h
//   3. WiFi + MQTT over TLS                          ← mqtt_client.h
//   4. Server: Node-RED → InfluxDB → Grafana
//   5. FastAPI + Telegram bot
// ─────────────────────────────────────────────────────────────────────────────

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <Ticker.h>

#include "src/drivers.h"
#include "src/occupancy.h"
#include "src/mqtt_client.h"

// ─── Timers ───────────────────────────────────────────────────────────────────
static const unsigned long SENSOR_POLL_MS   =   500;  // poll sensors every 500ms
static const unsigned long MQTT_PUBLISH_MS  = 30000;  // publish every 30s (+ on change)
static const unsigned long HEALTH_MS        = 60000;  // heartbeat every 60s
static const unsigned long DEBUG_MS         =  5000;  // serial debug every 5s

unsigned long lastSensorPoll   = 0;
unsigned long lastMQTTPublish  = 0;
unsigned long lastHealth       = 0;
unsigned long lastDebug        = 0;

// ─── Booking override ────────────────────────────────────────────────────────
// If a booking is active, room shows BUSY regardless of sensors
bool bookingActive = false;

void onBookingSync(const char* json) {
  // Simple: parse "active" field from booking sync message
  // Format: {"active": true/false, "until": "HH:MM"}
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, json) == DeserializationError::Ok) {
    bookingActive = doc["active"] | false;
    Serial.printf("[Booking] active=%d\n", bookingActive);
  }
}

// ─── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n\n=== Coworking Occupancy Monitor ===");

  // Enable watchdog — restarts device if loop() hangs for >8s
  ESP.wdtEnable(8000);

  // Init hardware drivers
  PIR::begin();
  Noise::begin();
  StatusLED::begin();
  Display::begin();

  // Blue LED = waiting for network
  StatusLED::setBlue();
  Display::showText("CONNECT ");

  // Connect WiFi + MQTT
  MQTTClient::onBookingSync = onBookingSync;
  MQTTClient::begin();

  // If connected: show current status; if not: go autonomous
  if (MQTTClient::isConnected()) {
    StatusLED::setGreen();
  } else {
    StatusLED::setYellow(); // Yellow = autonomous mode (no network)
    Display::showText("AUTONOM ");
  }

  Serial.println("[Setup] Ready.");
}

// ─── Loop ─────────────────────────────────────────────────────────────────────
void loop() {
  ESP.wdtFeed(); // pet the watchdog

  unsigned long now = millis();

  // ── 1. Poll sensors every 500ms ──────────────────────────────────────────
  if (now - lastSensorPoll >= SENSOR_POLL_MS) {
    lastSensorPoll = now;

    bool motion = PIR::read();
    bool noise  = Noise::read();

    bool statusChanged = OccupancyService::update(motion, noise);

    // Determine effective status (booking overrides sensors)
    OccupancyService::Status effectiveStatus =
      bookingActive ? OccupancyService::Status::BUSY
                    : OccupancyService::getStatus();

    // Update local indicators
    if (effectiveStatus == OccupancyService::Status::BUSY) {
      StatusLED::setRed();
      Display::showBusy();
    } else if (effectiveStatus == OccupancyService::Status::FREE) {
      StatusLED::setGreen();
      Display::showFree();
    }

    // Publish immediately on status change
    if (statusChanged && MQTTClient::isConnected()) {
      const char* s = (effectiveStatus == OccupancyService::Status::BUSY)
                      ? "busy" : "free";
      MQTTClient::publishStatus(s);
      MQTTClient::publishSensors(motion, noise);
      lastMQTTPublish = now;
    }
  }

  // ── 2. Periodic MQTT publish (every 30s) ─────────────────────────────────
  if (now - lastMQTTPublish >= MQTT_PUBLISH_MS) {
    lastMQTTPublish = now;
    if (MQTTClient::isConnected()) {
      OccupancyService::Status effectiveStatus =
        bookingActive ? OccupancyService::Status::BUSY
                      : OccupancyService::getStatus();
      const char* s = (effectiveStatus == OccupancyService::Status::BUSY)
                      ? "busy" : "free";
      MQTTClient::publishStatus(s);
      MQTTClient::publishSensors(
        OccupancyService::isMotion(),
        OccupancyService::isNoise()
      );
    }
  }

  // ── 3. Health heartbeat (every 60s) ──────────────────────────────────────
  if (now - lastHealth >= HEALTH_MS) {
    lastHealth = now;
    if (MQTTClient::isConnected()) {
      MQTTClient::publishHealth(MQTTClient::reconnectCount);
    }
  }

  // ── 4. MQTT loop (keep connection alive, process incoming) ───────────────
  MQTTClient::loop();

  // ── 5. Serial debug ──────────────────────────────────────────────────────
  if (now - lastDebug >= DEBUG_MS) {
    lastDebug = now;
    OccupancyService::printDebug();
    Serial.printf("[Net] WiFi RSSI=%d MQTT=%s booking=%d\n",
      WiFi.RSSI(),
      MQTTClient::isConnected() ? "OK" : "OFFLINE",
      bookingActive
    );
  }
}
