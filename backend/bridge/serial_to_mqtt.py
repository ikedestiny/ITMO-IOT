import serial
import paho.mqtt.client as mqtt
import json

# Setup MQTT (Talks to your Docker container)
client = mqtt.Client()
client.username_pw_set("server", "serverpass")
client.connect("localhost", 1883)

# Setup Serial (Talks to NodeMCU)
ser = serial.Serial('/dev/ttyUSB0', 115200)

print("Listening for NodeMCU events on USB...")
while True:
    if ser.in_waiting > 0:
        line = ser.readline().decode('utf-8').strip()
        if line == "OCCUPIED_EVENT":
            payload = json.dumps({"room_id": "room1", "status_str": "occupied"})
            client.publish("coworking/room1/occupancy", payload)
            print("Forwarded to MQTT: Occupied")
