import serial
import paho.mqtt.client as mqtt
import requests
import json
import os
import time
import threading

# --- Config ---
MQTT_BROKER = "localhost" # Since this runs on Fedora, use localhost for Docker port 1883
MQTT_PORT   = 1883
MQTT_USER   = "server"
MQTT_PASS   = "serverpass"
INFLUX_URL  = "http://localhost:8086" 
INFLUX_TOKEN = "my-super-secret-token"
INFLUX_ORG   = "coworking"
INFLUX_BUCKET = "occupancy"
SERIAL_PORT  = "/dev/ttyUSB0"
BAUD_RATE    = 115200

def write_influx(line):
    try:
        r = requests.post(
            f"{INFLUX_URL}/api/v2/write?org={INFLUX_ORG}&bucket={INFLUX_BUCKET}&precision=s",
            headers={"Authorization": f"Token {INFLUX_TOKEN}"},
            data=line,
            timeout=5
        )
        return r.status_code
    except Exception as e:
        print(f"Influx Error: {e}")
        return 500

# --- Serial Listener Thread ---
def serial_worker():
    print(f"Starting Serial Listener on {SERIAL_PORT}...")
    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                while True:
                    if ser.in_waiting > 0:
                        line = ser.readline().decode('utf-8').strip()
                        if line == "OCCUPIED_EVENT":
                            print("USB Event: Motion/Sound Detected")
                            # Manually write the same data your MQTT handler would
                            influx_line = 'occupancy,room_id=room1 status=1,status_str="busy"'
                            code = write_influx(influx_line)
                            print(f"USB Event -> InfluxDB {code}")
        except Exception as e:
            print(f"Serial Port Error: {e}. Retrying in 5s...")
            time.sleep(5)

# --- MQTT Logic ---
def on_message(client, userdata, msg):
    # (Keep your existing MQTT logic here for when you use Wi-Fi later)
    try:
        payload = json.loads(msg.payload)
        topic_parts = msg.topic.split('/')
        room_id = topic_parts[1] if len(topic_parts) > 1 else "room1"
        
        if "occupancy" in msg.topic:
            status = payload.get("status_str", "unknown")
            status_int = 1 if status == "busy" or status == "occupied" else 0
            line = f'occupancy,room_id={room_id} status={status_int},status_str="{status}"'
            write_influx(line)
    except: pass

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker (rc={rc})")
    client.subscribe("coworking/#")

# --- Start Threads ---
# Start Serial in a background thread
t = threading.Thread(target=serial_worker, daemon=True)
t.start()

# Start MQTT in the main thread
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message

while True:
    try:
        client.connect(MQTT_BROKER, MQTT_PORT)
        client.loop_forever()
    except Exception as e:
        print(f"MQTT failed: {e}, retrying...")
        time.sleep(5)
