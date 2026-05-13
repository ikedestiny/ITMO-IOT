#include <Arduino.h>

const int soundPin = 5; // D1 on NodeMCU (GPIO 5)

void setup() {
  Serial.begin(115200);
  pinMode(soundPin, INPUT);
}

void loop() {
  // Most 3-pin FC-04s are "Active LOW": 
  // They stay HIGH (1) and drop to LOW (0) when sound is detected.
  int sensorState = digitalRead(soundPin);

  if (sensorState == LOW) {
    Serial.println("!!! SOUND DETECTED !!!");
    delay(200); // Small debounce to avoid multiple triggers
  }
}
  