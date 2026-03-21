import paho.mqtt.client as mqtt
import requests
import json
import os
import time

MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER", "server")
MQTT_PASS = os.getenv("MQTT_PASS", "serverpass")
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "my-super-secret-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "coworking")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "occupancy")

def write_influx(line):
    r = requests.post(
        f"{INFLUX_URL}/api/v2/write?org={INFLUX_ORG}&bucket={INFLUX_BUCKET}&precision=s",
        headers={"Authorization": f"Token {INFLUX_TOKEN}"},
        data=line
    )
    return r.status_code

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        topic_parts = msg.topic.split('/')
        room_id = topic_parts[1] if len(topic_parts) > 1 else "room1"

        if "status" in msg.topic and "sensors" not in msg.topic:
            status = payload.get("status", "unknown")
            status_int = 1 if status == "busy" else 0
            line = f'occupancy,room_id={room_id} status={status_int},status_str="{status}"'
            code = write_influx(line)
            print(f"[{msg.topic}] {status} -> InfluxDB {code}")

        elif "sensors/motion" in msg.topic:
            value = 1 if payload.get("value") else 0
            line = f'sensors,room_id={room_id},sensor_type=motion value={value}'
            write_influx(line)

        elif "sensors/noise" in msg.topic:
            value = 1 if payload.get("value") else 0
            line = f'sensors,room_id={room_id},sensor_type=noise value={value}'
            write_influx(line)

        elif "device/health" in msg.topic:
            rssi = payload.get("rssi", 0)
            uptime = payload.get("uptime", 0)
            online = 1 if payload.get("status") == "online" else 0
            line = f'device_health,room_id={room_id} online={online},rssi={rssi},uptime={uptime}'
            write_influx(line)

    except Exception as e:
        print(f"Error: {e}")

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker (rc={rc})")
    client.subscribe("coworking/#")

client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message

while True:
    try:
        client.connect(MQTT_BROKER, MQTT_PORT)
        client.loop_forever()
    except Exception as e:
        print(f"Connection failed: {e}, retrying in 5s...")
        time.sleep(5)
