#include <Arduino.h>
#include <Wire.h>
#include <Keypad_I2C.h>
#include <Keypad.h>

// --- Pin Allocations ---
#define I2C_SDA D2     // NodeMCU GPIO4 (Hardware I2C SDA)
#define I2C_SCL D1     // NodeMCU GPIO5 (Hardware I2C SCL)
#define PIR_PIN D5     // NodeMCU GPIO14 (Relocated to prevent conflict)
#define SOUND_PIN D6   // NodeMCU GPIO12 (Relocated to prevent conflict)
#define STATUS_LED 2   // NodeMCU On-board LED (Active-LOW)

#define I2CADDR 0x20

// --- Sensor Settings ---
const unsigned long COOLDOWN_MS = 5000; 
unsigned long lastEventTime = 0;        

// --- Keypad Configuration ---
boolean blink = false;
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

Keypad_I2C keypad = Keypad_I2C(makeKeymap(keys), rowPins, colPins, ROWS, COLS, I2CADDR);

void keypadEvent(KeypadEvent key){
  switch (keypad.getState()){
    case PRESSED:
      switch (key){
        case '#': digitalWrite(STATUS_LED, !digitalRead(STATUS_LED)); break;
        case '*': digitalWrite(STATUS_LED, !digitalRead(STATUS_LED)); break;
      }
    break;
    case RELEASED:
      switch (key){
        case '*': 
          digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
          blink = false;
        break;
      }
    break;
    case HOLD:
      switch (key){
        case '*': blink = true; break;
      }
    break;
    default:
    break;
  }
}

void setup(){
  Serial.begin(115200); 
  while(!Serial); 
  
  // 1. Initialize Peripheral Buses & Hardware Components
  Wire.begin(I2C_SDA, I2C_SCL);
  pinMode(PIR_PIN, INPUT);
  pinMode(SOUND_PIN, INPUT);
  pinMode(STATUS_LED, OUTPUT);      
  digitalWrite(STATUS_LED, HIGH);   

  // 2. Refresh PCF8574 Internal Direct Port Registers
  Wire.beginTransmission(I2CADDR);
  Wire.write(0xFF); 
  Wire.endTransmission();

  // 3. Initialize Drivers & Callbacks
  keypad.begin();          
  keypad.addEventListener(keypadEvent); 
  
  Serial.println("SYSTEM_READY");
}

void loop(){
  unsigned long currentTime = millis();

  // --- Keypad Processing Section ---
  char key = keypad.getKey();
  if (key) {
    Serial.printf("KEYPAD_EVENT:%c\n", key);
  }
  
  // --- Sensor Logic Section (Non-blocking Cooldown Window) ---
  if (currentTime - lastEventTime >= COOLDOWN_MS) {
    bool motion = (digitalRead(PIR_PIN) == HIGH);
    bool sound = (digitalRead(SOUND_PIN) == LOW);

    if (motion || sound) {
      Serial.println("OCCUPIED_EVENT");
      lastEventTime = currentTime; // Mark event timestamp to begin tracking window
    }
  }

  // --- LED Feedback Execution Loop ---
  if (blink){
    static unsigned long lastBlinkTime = 0;
    if (currentTime - lastBlinkTime >= 100) {
      digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
      lastBlinkTime = currentTime;
    }
  }
  
  delay(10); // Standard scheduler delay for background tasks
}
