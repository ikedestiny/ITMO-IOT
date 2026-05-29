FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install \
    paho-mqtt \
    requests \
    pyserial \
    influxdb-client

COPY bridge.py .

CMD ["python", "bridge.py"]