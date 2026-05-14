import serial, time
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
time.sleep(2)  # wait for bootloader
print("Listening...")
while True:
    line = ser.readline()
    if line:
        print(repr(line))