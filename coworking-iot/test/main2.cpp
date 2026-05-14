#include <Arduino.h>
#include <Wire.h>
#include <Keypad_I2C.h>
#include <Keypad.h>

// =========================
// I2C Pins for Keypad
// =========================
#define I2C_SDA D2   // GPIO4
#define I2C_SCL D1   // GPIO5

// =========================
// Sensor Pins
// =========================
#define PIR_PIN   D5 // GPIO14
#define SOUND_PIN D6 // GPIO12

// =========================
// PCF8574 I2C Address
// =========================
#define I2CADDR 0x20

// =========================
// Cooldown
// =========================
const unsigned long COOLDOWN_MS = 3000;
unsigned long lastEventTime = 0;

// =========================
// Keypad Configuration
// =========================
const byte ROWS = 4;
const byte COLS = 3;

char keys[ROWS][COLS] = {
  {'1','2','3'},
  {'4','5','6'},
  {'7','8','9'},
  {'*','0','#'}
};

byte rowPins[ROWS] = {0, 1, 2, 3};
byte colPins[COLS] = {4, 5, 6};

Keypad_I2C keypad(
  makeKeymap(keys),
  rowPins,
  colPins,
  ROWS,
  COLS,
  I2CADDR
);

void setup() {

  Serial.begin(115200);
  delay(100);

  // =========================
  // I2C Initialization
  // =========================
  Wire.begin(I2C_SDA, I2C_SCL);

  // =========================
  // Sensor Pins
  // =========================
  pinMode(PIR_PIN, INPUT);
  pinMode(SOUND_PIN, INPUT);

  // =========================
  // Initialize PCF8574
  // =========================
  Wire.beginTransmission(I2CADDR);
  Wire.write(0xFF);
  Wire.endTransmission();

  // =========================
  // Start Keypad
  // =========================
  keypad.begin();

  // =========================
  // PIR Warmup
  // =========================
  Serial.println("Warming up PIR...");
  delay(30000);

  Serial.println("SYSTEM_READY");
}

void loop() {

  unsigned long currentTime = millis();

  // =========================
  // Keypad
  // =========================
  char key = keypad.getKey();

  if (key) {
    Serial.print("KEYPAD:");
    Serial.println(key);
  }

  // =========================
  // Sensor Logic
  // =========================
  if (currentTime - lastEventTime >= COOLDOWN_MS) {

    int pirState = digitalRead(PIR_PIN);
    int soundState = digitalRead(SOUND_PIN);

    // Debug
    
    Serial.print("PIR: ");
    Serial.print(pirState);

    Serial.print(" | SOUND: ");
    Serial.println(soundState);
    

    // PIR: HIGH when motion detected
    if (pirState == HIGH) {
      Serial.println("MOTION_DETECTED");
      lastEventTime = currentTime;
    }

    // Sound module: LOW when sound detected
    if (soundState == ) {
      Serial.println("SOUNDLOW_DETECTED");
      lastEventTime = currentTime;
    }
  }

  delay(10);
}