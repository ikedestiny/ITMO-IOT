#pragma once
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ─── MQTT Client ─────────────────────────────────────────────────────────────
// Handles: WiFi, TLS, MQTT connect/reconnect, LWT, publish, subscribe

namespace MQTTClient {

  // ── Config (edit these) ───────────────────────────────────────────────────
  static const char* WIFI_SSID     = "YOUR_WIFI_SSID";
  static const char* WIFI_PASS     = "YOUR_WIFI_PASSWORD";
  static const char* MQTT_HOST     = "YOUR_SERVER_IP";   // e.g. "192.168.1.100"
  static const int   MQTT_PORT     = 8883;               // TLS port
  static const char* MQTT_USER     = "device";
  static const char* MQTT_PASS     = "devicepass";
  static const char* ROOM_ID       = "room1";            // unique per room
  static const char* DEVICE_ID     = "esp8266-room1";

  // ── TLS: paste CA cert from mosquitto/certs/ca.crt ───────────────────────
  // Generate with: bash server/setup.sh
  static const char CA_CERT[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE_YOUR_CA_CERT_HERE
-----END CERTIFICATE-----
)EOF";

  // ── Topics (auto-built from ROOM_ID) ──────────────────────────────────────
  char topicStatus[48];
  char topicMotion[48];
  char topicNoise[48];
  char topicHealth[48];
  char topicBooking[48];

  // ── Internal ──────────────────────────────────────────────────────────────
  WiFiClientSecure  wifiClient;
  PubSubClient      client(wifiClient);
  X509List          caCert(CA_CERT);

  unsigned long lastReconnectAttempt = 0;
  int           reconnectCount       = 0;
  unsigned long connectTime          = 0;

  // Booking sync callback — set by main.ino
  std::function<void(const char*)> onBookingSync = nullptr;

  // ── Internal: message callback ────────────────────────────────────────────
  void _onMessage(char* topic, byte* payload, unsigned int length) {
    char buf[256];
    length = min(length, (unsigned int)sizeof(buf) - 1);
    memcpy(buf, payload, length);
    buf[length] = '\0';

    if (strcmp(topic, topicBooking) == 0 && onBookingSync) {
      onBookingSync(buf);
    }
  }

  // ── Connect to WiFi ───────────────────────────────────────────────────────
  void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;
    Serial.printf("\n[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
      delay(500);
      Serial.print(".");
      attempts++;
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("\n[WiFi] Connected: %s\n", WiFi.localIP().toString().c_str());
      configTime(0, 0, "pool.ntp.org"); // Required for TLS cert validation
    } else {
      Serial.println("\n[WiFi] Failed — will retry");
    }
  }

  // ── Connect to MQTT broker ────────────────────────────────────────────────
  bool connectMQTT() {
    // Build LWT payload
    StaticJsonDocument<128> lwt;
    lwt["status"]  = "offline";
    lwt["room_id"] = ROOM_ID;
    char lwtBuf[128];
    serializeJson(lwt, lwtBuf);

    if (client.connect(DEVICE_ID, MQTT_USER, MQTT_PASS,
                       topicHealth, 1, true, lwtBuf)) {
      Serial.println("[MQTT] Connected");
      reconnectCount++;
      connectTime = millis();

      // Subscribe to booking sync
      client.subscribe(topicBooking, 1);

      // Announce online
      StaticJsonDocument<128> hello;
      hello["status"]  = "online";
      hello["room_id"] = ROOM_ID;
      char helloBuf[128];
      serializeJson(hello, helloBuf);
      client.publish(topicHealth, helloBuf, true);

      return true;
    }
    Serial.printf("[MQTT] Failed, rc=%d\n", client.state());
    return false;
  }

  // ── begin() — call from setup() ──────────────────────────────────────────
  void begin() {
    // Build topic strings
    snprintf(topicStatus,  sizeof(topicStatus),  "coworking/%s/status",         ROOM_ID);
    snprintf(topicMotion,  sizeof(topicMotion),  "coworking/%s/sensors/motion", ROOM_ID);
    snprintf(topicNoise,   sizeof(topicNoise),   "coworking/%s/sensors/noise",  ROOM_ID);
    snprintf(topicHealth,  sizeof(topicHealth),  "coworking/%s/device/health",  ROOM_ID);
    snprintf(topicBooking, sizeof(topicBooking), "coworking/%s/booking/sync",   ROOM_ID);

    // TLS
    wifiClient.setTrustAnchors(&caCert);
    // wifiClient.setInsecure(); // Uncomment to skip TLS verify during dev

    client.setServer(MQTT_HOST, MQTT_PORT);
    client.setCallback(_onMessage);
    client.setKeepAlive(60);
    client.setBufferSize(512);

    connectWiFi();
    connectMQTT();
  }

  // ── loop() — call from Arduino loop() ────────────────────────────────────
  void loop() {
    if (WiFi.status() != WL_CONNECTED) {
      connectWiFi();
      return;
    }
    if (!client.connected()) {
      unsigned long now = millis();
      // Exponential back-off: 5s, 10s, 20s ... up to 60s
      unsigned long delay_ms = min(5000UL * (1 << min(reconnectCount, 4)), 60000UL);
      if (now - lastReconnectAttempt > delay_ms) {
        lastReconnectAttempt = now;
        connectMQTT();
      }
      return;
    }
    client.loop();
  }

  bool isConnected() { return client.connected(); }

  // ── Publish status ────────────────────────────────────────────────────────
  void publishStatus(const char* status) {
    StaticJsonDocument<128> doc;
    doc["status"]    = status;
    doc["room_id"]   = ROOM_ID;
    doc["timestamp"] = millis();
    char buf[128];
    serializeJson(doc, buf);
    client.publish(topicStatus, buf, /*retain=*/true);
    Serial.printf("[MQTT] Published status: %s\n", status);
  }

  // ── Publish raw sensor readings ───────────────────────────────────────────
  void publishSensors(bool motion, bool noise) {
    StaticJsonDocument<64> m;
    m["value"] = motion;
    m["raw"]   = motion ? 1 : 0;
    char buf[64];
    serializeJson(m, buf);
    client.publish(topicMotion, buf);

    StaticJsonDocument<64> n;
    n["value"] = noise;
    n["raw"]   = noise ? 1 : 0;
    serializeJson(n, buf);
    client.publish(topicNoise, buf);
  }

  // ── Publish heartbeat ─────────────────────────────────────────────────────
  void publishHealth(int reconnects) {
    StaticJsonDocument<128> doc;
    doc["status"]     = "online";
    doc["room_id"]    = ROOM_ID;
    doc["rssi"]       = WiFi.RSSI();
    doc["uptime"]     = millis() / 1000;
    doc["reconnects"] = reconnects;
    char buf[128];
    serializeJson(doc, buf);
    client.publish(topicHealth, buf, true);
  }
}
