FROM python:3.11-slim
WORKDIR /app
RUN pip install paho-mqtt requests
COPY bridge.py .
CMD ["python", "bridge.py"]