#pragma once
#include <Arduino.h>
#include <FastLED.h>
#include <TM1638plus.h>

// ─── Pin Definitions ──────────────────────────────────────────────────────────
#define PIN_PIR       D5   // HC-SR501 digital output
#define PIN_NOISE     D6   // FC-04 digital output
#define PIN_LED_DATA  D7   // WS2812B data line
#define PIN_TM_STB    D8   // TM1638 strobe
#define PIN_TM_CLK    D4   // TM1638 clock
#define PIN_TM_DIO    D3   // TM1638 data I/O

// ─── LED Config ───────────────────────────────────────────────────────────────
#define NUM_LEDS      1
#define LED_BRIGHTNESS 80  // 0-255, keep low to not blind people

CRGB leds[NUM_LEDS];

// ─── Display ──────────────────────────────────────────────────────────────────
TM1638plus tm(PIN_TM_STB, PIN_TM_CLK, PIN_TM_DIO);

// ─── Driver: PIR sensor (HC-SR501) ───────────────────────────────────────────
namespace PIR {
  void begin() {
    pinMode(PIN_PIR, INPUT);
  }

  // Returns true if motion detected
  bool read() {
    return digitalRead(PIN_PIR) == HIGH;
  }
}

// ─── Driver: Noise sensor (FC-04) ────────────────────────────────────────────
namespace Noise {
  void begin() {
    pinMode(PIN_NOISE, INPUT);
  }

  // Returns true if noise above threshold
  // Threshold is set via potentiometer on the FC-04 module
  bool read() {
    return digitalRead(PIN_NOISE) == LOW; // FC-04 outputs LOW on detection
  }
}

// ─── Driver: WS2812B RGB LED ─────────────────────────────────────────────────
namespace StatusLED {
  void begin() {
    FastLED.addLeds<WS2812B, PIN_LED_DATA, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(LED_BRIGHTNESS);
    setBlue(); // startup color = no data
  }

  void setGreen() {
    leds[0] = CRGB::Green;
    FastLED.show();
  }

  void setRed() {
    leds[0] = CRGB::Red;
    FastLED.show();
  }

  void setBlue() {
    leds[0] = CRGB::Blue;
    FastLED.show();
  }

  void setYellow() {
    leds[0] = CRGB::Yellow;
    FastLED.show();
  }

  void off() {
    leds[0] = CRGB::Black;
    FastLED.show();
  }
}

// ─── Driver: TM1638 Display ──────────────────────────────────────────────────
namespace Display {
  void begin() {
    tm.displayBegin();
    showText("BOOT    ");
  }

  // Show up to 8 characters (pad with spaces)
  void showText(const char* text) {
    tm.displayText(text);
  }

  void showFree() {
    tm.displayText("FREE    ");
  }

  void showBusy() {
    tm.displayText("BUSY    ");
  }

  void showOffline() {
    tm.displayText("OFFLINE ");
  }

  // Show a number (e.g. minutes remaining)
  void showNumber(int n) {
    tm.displayIntNum(n, true);
  }
}
