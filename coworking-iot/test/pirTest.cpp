#include <Arduino.h>

#define PIR_PIN 4  // D2 on NodeMCU

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  Serial.println("Warming up 30s...");
  delay(30000);
  Serial.println("Ready. Wave your hand!");
}

void loop() {
  int state = digitalRead(PIR_PIN);
  
  if (state == HIGH) {
    Serial.println("[PIR] Motion DETECTED — HIGH");
    delay(2000);  // Wait 2 seconds after detection
  } else {
    Serial.println("[PIR] No motion — LOW");
    delay(500);
  }
}