"""Servo hardware manager extracted from the original monolith.
Provides a thread-safe queue-based interface for sending servo move commands
and a safe emergency stop.

This module deliberately keeps hardware initialization inside the thread so
that importing the module on a dev machine without I2C won't raise.
"""

import threading
import queue
import time
from typing import Dict

class ServoManager:
    def __init__(self):
        self.hardware_available = False
        self.servos: Dict[int, dict] = {}
        self.command_queue = queue.Queue()
        self.running = True
        self._lock = threading.Lock()

        self.thread = threading.Thread(target=self._hardware_loop, name="HardwareThread")
        self.thread.daemon = True
        self.thread.start()

    def _init_hardware(self) -> bool:
        try:
            import board
            import busio
            from adafruit_pca9685 import PCA9685
            from adafruit_motor import servo

            i2c = busio.I2C(board.SCL, board.SDA)
            pca = PCA9685(i2c, address=0x40)
            pca.frequency = 50

            for ch in range(5):
                try:
                    s = servo.Servo(pca.channels[ch], min_pulse=500, max_pulse=2500)
                    self.servos[ch] = {"obj": s, "pca": pca}
                except Exception as e:
                    print(f"⚠️ Kanal {ch} Init-Fehler: {e}")
                    self.servos[ch] = None

            self.hardware_available = True
            print("✅ Hardware initialisiert")
            return True
        except Exception as e:
            print(f"❌ Hardware-Init-Fehler (Simulationsmodus): {e}")
            self.hardware_available = False
            return False

    def _hardware_loop(self):
        print("🚀 Hardware-Thread startet...")
        if not self._init_hardware():
            print("⚠️ Hardware nicht verfügbar — laufe im Simulationsmodus")

        while self.running:
            try:
                cmd = self.command_queue.get(timeout=0.1)
                if cmd["type"] == "move":
                    ch = cmd["channel"]
                    angle = cmd["angle"]
                    if self.hardware_available and ch in self.servos and self.servos[ch]:
                        try:
                            self.servos[ch]["obj"].angle = angle
                            print(f"📡 Kanal {ch} → {angle}°")
                        except Exception as e:
                            print(f"❌ Fehler beim Schreiben auf Kanal {ch}: {e}")
                elif cmd["type"] == "stop":
                    print("⛔ Not-Aus: setze alle Servos auf Home")
                    if self.hardware_available:
                        for ch in list(self.servos.keys()):
                            if self.servos.get(ch):
                                try:
                                    self.servos[ch]["obj"].angle = 90
                                except Exception:
                                    pass
                    with self._lock:
                        try:
                            while True:
                                self.command_queue.get_nowait()
                                self.command_queue.task_done()
                        except queue.Empty:
                            pass

                self.command_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ Hardware-Thread Exception: {e}")

    def move_servo(self, channel: int, angle: int):
        try:
            ch = int(channel)
        except Exception:
            return
        if ch < 0 or ch > 15:
            return
        self.command_queue.put({"type": "move", "channel": ch, "angle": int(angle)})

    def emergency_stop(self):
        with self._lock:
            try:
                while True:
                    self.command_queue.get_nowait()
                    self.command_queue.task_done()
            except queue.Empty:
                pass
            self.command_queue.put({"type": "stop"})

    def stop(self):
        self.running = False
        self.thread.join(timeout=1.0)
