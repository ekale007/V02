#!/usr/bin/env python3
"""Simple PCA9685 servo test script.
Writes a few angles to channel 0 so you can observe the signal/servo.
Run on the Pi: python3 scripts/pwm_test.py
"""
import time
try:
    import board
    import busio
    from adafruit_pca9685 import PCA9685
    from adafruit_motor import servo
except Exception as e:
    print('Required hardware libs missing:', e)
    raise

print('Initializing I2C and PCA9685...')
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c, address=0x40)
pca.frequency = 50

ch = 0
print('Creating Servo object on channel', ch)
s = servo.Servo(pca.channels[ch])

try:
    for angle in (60, 120, 90):
        print('Setting angle', angle)
        try:
            s.angle = angle
        except Exception as e:
            print('Write exception:', e)
        time.sleep(1.0)
    print('Done test sequence')
finally:
    try:
        pca.deinit()
    except Exception:
        pass
