#include <Arduino.h>

#define PIR_PIN 5   // D1
#define SOUND_PIN 4 // D2

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  pinMode(SOUND_PIN, INPUT);
  Serial.println("SYSTEM_READY");
}

void loop() {
  bool motion = (digitalRead(PIR_PIN) == HIGH);
  bool sound = (digitalRead(SOUND_PIN) == LOW);

  if (motion || sound) {
    // Send a simple trigger to Fedora via USB
    Serial.println("OCCUPIED_EVENT");
    delay(5000); // Cooldown
  }
}
