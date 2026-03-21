#pragma once
#include <Arduino.h>

// ─── Occupancy Service ────────────────────────────────────────────────────────
// Implements a 5-minute sliding window:
//   - Room is BUSY if any sensor triggered in the last WINDOW_MS
//   - Hysteresis prevents rapid FREE/BUSY flipping
//   - Status only changes after HYSTERESIS_MS of stable readings

namespace OccupancyService {

  // ── Config ────────────────────────────────────────────────────────────────
  static const unsigned long WINDOW_MS     = 5UL * 60 * 1000; // 5 min
  static const unsigned long HYSTERESIS_MS = 30UL * 1000;     // 30 sec
  static const unsigned long POLL_MS       = 500;             // sensor poll rate

  // ── State ─────────────────────────────────────────────────────────────────
  enum class Status { UNKNOWN, FREE, BUSY };

  static Status  currentStatus   = Status::UNKNOWN;
  static Status  pendingStatus   = Status::UNKNOWN;
  static unsigned long lastMotionTime  = 0;
  static unsigned long lastNoiseTime   = 0;
  static unsigned long pendingSince    = 0;

  // Raw sensor readings (for MQTT publishing)
  static bool    lastMotionRaw   = false;
  static bool    lastNoiseRaw    = false;

  // ── Getters ───────────────────────────────────────────────────────────────
  Status getStatus()     { return currentStatus; }
  bool   isMotion()      { return lastMotionRaw; }
  bool   isNoise()       { return lastNoiseRaw; }

  const char* statusString() {
    switch (currentStatus) {
      case Status::BUSY:    return "busy";
      case Status::FREE:    return "free";
      default:              return "unknown";
    }
  }

  // ── Core update — call every POLL_MS ─────────────────────────────────────
  // motionDetected: raw reading from PIR::read()
  // noiseDetected:  raw reading from Noise::read()
  // Returns true if status changed (caller should publish MQTT)
  bool update(bool motionDetected, bool noiseDetected) {
    unsigned long now = millis();

    lastMotionRaw = motionDetected;
    lastNoiseRaw  = noiseDetected;

    // Extend the window on any detection
    if (motionDetected) lastMotionTime = now;
    if (noiseDetected)  lastNoiseTime  = now;

    // Is anything within the window?
    bool motionInWindow = (now - lastMotionTime) < WINDOW_MS;
    bool noiseInWindow  = (now - lastNoiseTime)  < WINDOW_MS;
    Status rawStatus = (motionInWindow || noiseInWindow) ? Status::BUSY : Status::FREE;

    // Apply hysteresis: only commit to change after HYSTERESIS_MS
    if (rawStatus != pendingStatus) {
      pendingStatus = rawStatus;
      pendingSince  = now;
    }

    bool changed = false;
    if (pendingStatus != currentStatus) {
      if ((now - pendingSince) >= HYSTERESIS_MS) {
        currentStatus = pendingStatus;
        changed = true;
      }
    }

    // Bootstrap: if we have no status yet, set immediately (no hysteresis)
    if (currentStatus == Status::UNKNOWN && rawStatus != Status::UNKNOWN) {
      currentStatus = rawStatus;
      pendingStatus = rawStatus;
      changed = true;
    }

    return changed;
  }

  // ── Debug ─────────────────────────────────────────────────────────────────
  void printDebug() {
    unsigned long now = millis();
    Serial.printf("[OccupancySvc] status=%s motion=%d noise=%d "
                  "motionAge=%lus noiseAge=%lus\n",
      statusString(),
      lastMotionRaw, lastNoiseRaw,
      (now - lastMotionTime) / 1000,
      (now - lastNoiseTime)  / 1000
    );
  }
}
