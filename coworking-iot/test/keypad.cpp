#include <Arduino.h>
#include <Wire.h>
#include <Keypad_I2C.h>
#include <Keypad.h>

#define I2C_SDA D2  // NodeMCU GPIO4
#define I2C_SCL D1  // NodeMCU GPIO5
#define I2CADDR 0x20 // Updated to match your scanner's real hardware address output

byte ledPin = 2; // NodeMCU on-board status LED (Active-LOW)
boolean blink = false;

const byte ROWS = 4; 
const byte COLS = 3; 
char keys[ROWS][COLS] = {
  {'1','2','3'},
  {'4','5','6'},
  {'7','8','9'},
  {'*','0','#'}
};

// Standard wiring configuration for common PCF8574 I2C adapter backpacks
byte rowPins[ROWS] = {0, 1, 2, 3}; 
byte colPins[COLS] = {4, 5, 6}; 

Keypad_I2C keypad = Keypad_I2C(makeKeymap(keys), rowPins, colPins, ROWS, COLS, I2CADDR);

void keypadEvent(KeypadEvent key){
  switch (keypad.getState()){
    case PRESSED:
      switch (key){
        case '#': digitalWrite(ledPin, !digitalRead(ledPin)); break;
        case '*': digitalWrite(ledPin, !digitalRead(ledPin)); break;
      }
    break;
    case RELEASED:
      switch (key){
        case '*': 
          digitalWrite(ledPin, !digitalRead(ledPin));
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
  
  // 1. Fire up physical I2C pins using explicit NodeMCU assignments
  Wire.begin(I2C_SDA, I2C_SCL);
  
  // 2. Clear out the PCF8574 internal registers to configure all pins as inputs
  Wire.beginTransmission(I2CADDR);
  Wire.write(0xFF); 
  Wire.endTransmission();

  // 3. Initialize the Keypad library state framework engines
  keypad.begin();          
  
  pinMode(ledPin, OUTPUT);      
  digitalWrite(ledPin, HIGH);   
  keypad.addEventListener(keypadEvent); 
  
  Serial.println("System fully active. Press your physical keypad buttons now...");
}

void loop(){
  // Force a scan of the I2C port registers
  char key = keypad.getKey();
  
  if (key) {
    Serial.printf("Physical interaction tracked: %c\n", key);
  }
  
  if (blink){
    digitalWrite(ledPin, !digitalRead(ledPin));
    delay(100);
  }
  
  delay(20); // Small delay to satisfy ESP8266 background Wi-Fi/Watchdog loops
}
