#!/bin/bash
# Run this once to set up credentials and TLS certificates
# Usage: bash setup.sh

set -e
cd "$(dirname "$0")"

echo "=== Setting up Mosquitto credentials ==="
# Creates hashed passwords for two users:
#   device  / devicepass  -> used by ESP8266
#   server  / serverpass  -> used by Node-RED, FastAPI, Telegram bot
docker run --rm -v "$PWD/mosquitto/config:/mosquitto/config" \
  eclipse-mosquitto:2 \
  sh -c "
    mosquitto_passwd -c -b /mosquitto/config/passwd device devicepass &&
    mosquitto_passwd -b /mosquitto/config/passwd server serverpass &&
    echo 'Passwords written to mosquitto/config/passwd'
  "

echo ""
echo "=== Generating self-signed TLS certificates ==="
mkdir -p mosquitto/certs
cd mosquitto/certs

# CA key + cert
openssl genrsa -out ca.key 2048
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
  -subj "/CN=CoworkingCA"

# Server key + cert signed by CA
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/CN=mosquitto"
openssl x509 -req -days 3650 -in server.csr \
  -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt

# Copy CA cert for the ESP8266 firmware
cp ca.crt ../../firmware/certs/ca.crt

echo ""
echo "=== Done! ==="
echo "Credentials: device/devicepass  and  server/serverpass"
echo "TLS certs generated in mosquitto/certs/"
echo "CA cert copied to firmware/certs/ca.crt  (flash this to ESP8266)"
echo ""
echo "Now run: docker compose up -d"
