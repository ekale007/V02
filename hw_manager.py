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
import os
import json

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

    def _load_calib_pulses(self):
        try:
            cfg_path = os.path.join(os.path.dirname(__file__), "calib.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    c = json.load(f)
                pulses = c.get("pulse", {})
                return pulses
        except Exception as e:
            print("⚠️ Fehler beim Laden von calib.json für Pulsweiten:", e)
        return {}

    def _init_hardware(self) -> bool:
        try:
            import board
            import busio
            from adafruit_pca9685 import PCA9685
            from adafruit_motor import servo
            import ui_config as ui_cfg

            pulses = self._load_calib_pulses()
            # build channel -> joint map from ui_config
            channel_to_joint = {v: k for k, v in ui_cfg.SERVO_MAP.items()}

            i2c = busio.I2C(board.SCL, board.SDA)
            pca = PCA9685(i2c, address=0x40)
            pca.frequency = 50

            for ch in range(5):
                try:
                    joint = channel_to_joint.get(ch)
                    # default pulse values
                    min_p = 500
                    max_p = 2500
                    if joint and isinstance(pulses, dict):
                        pj = pulses.get(joint)
                        if isinstance(pj, dict):
                            min_p = int(pj.get("min_pulse", min_p))
                            max_p = int(pj.get("max_pulse", max_p))
                    print(f"🔧 Kanal {ch} ({joint}) Pulswerte: min={min_p} max={max_p}")
                    s = servo.Servo(pca.channels[ch], min_pulse=min_p, max_pulse=max_p)
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
