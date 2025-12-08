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
        # store last-known angles per channel for smooth moves
        self._last_angles: Dict[int, float] = {}
        self.command_queue = queue.Queue()
        self.running = True
        self._lock = threading.Lock()

        self.thread = threading.Thread(target=self._hardware_loop, name="HardwareThread")
        self.thread.daemon = True
        self.thread.start()
        # build a channel->joint map from UI config for per-joint lookups
        try:
            import ui_config as ui_cfg
            self.channel_to_joint = {v: k for k, v in ui_cfg.SERVO_MAP.items()}
        except Exception:
            self.channel_to_joint = {}

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

    def _load_calib_motion(self):
        """Load per-joint motion tuning from `calib.json` (returns dict)."""
        try:
            cfg_path = os.path.join(os.path.dirname(__file__), "calib.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    c = json.load(f)
                motion = c.get("motion", {})
                return motion if isinstance(motion, dict) else {}
        except Exception as e:
            print("⚠️ Fehler beim Laden von calib.json für motion tuning:", e)
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
                print(f"🔁 Hardware-Thread: empfangenes Kommando: {cmd}")
                if cmd["type"] == "move":
                    ch = cmd["channel"]
                    angle = int(cmd.get("angle"))
                    speed = cmd.get("speed")
                    # Map `speed` (1..100) to degrees-per-second and compute duration
                    # Use a larger step interval to avoid high-frequency tiny updates
                    def _speed_to_dps(s, channel=None):
                        try:
                            s = int(s)
                        except Exception:
                            s = 50
                        s = max(1, min(100, s))
                        # Use a geometric/exponential mapping for perceptual control:
                        # slowest: higher than before so 1% still moves noticeably,
                        # fastest: allow a larger max so 100% is clearly faster than 50%.
                        # Tuned mapping for perceptual separation:
                        # increase low-end speed and cap the top speed to reduce jitter.
                        # default fallbacks
                        min_dps = 12.0
                        max_dps = 360.0
                        try:
                            # attempt to read per-joint motion tuning from calib.json
                            motion = self._load_calib_motion()
                            if channel is not None and isinstance(self.channel_to_joint, dict):
                                joint = self.channel_to_joint.get(channel)
                                if joint and isinstance(motion, dict):
                                    mj = motion.get(joint)
                                    if isinstance(mj, dict):
                                        # prefer explicit per-joint values when present
                                        if mj.get('min_dps') is not None:
                                            min_dps = float(mj.get('min_dps'))
                                        if mj.get('max_dps') is not None:
                                            max_dps = float(mj.get('max_dps'))
                        except Exception:
                            pass
                        # geometric interpolation: min * (ratio)^(p) where p = s/100
                        ratio = max_dps / min_dps
                        p = s / 100.0
                        return min_dps * (ratio ** p)

                    if self.hardware_available and ch in self.servos and self.servos[ch]:
                        try:
                            # get current angle if known, otherwise try to read from object
                            cur = self._last_angles.get(ch)
                            if cur is None:
                                try:
                                    cur = float(self.servos[ch]["obj"].angle)
                                except Exception:
                                    cur = float(angle)
                            # If there is a newer move for the same channel queued, skip this older command
                            try:
                                # access underlying deque (non-public) to detect newer moves
                                pending = list(self.command_queue.queue)
                                newer = any((p.get("type") == "move" and p.get("channel") == ch) for p in pending)
                                if newer:
                                    # skip this stale move in favor of the newer one(s)
                                    self.command_queue.task_done()
                                    continue
                            except Exception:
                                pass

                            deg = abs(angle - cur)
                            # only attempt smoothing for meaningful moves
                            if speed is not None and deg > 0.5:
                                dps = _speed_to_dps(speed, channel=ch)
                                # compute duration based on degrees / deg-per-sec
                                duration = max(0.0, deg / dps)
                                # choose a conservative step interval (lower update rate reduces jitter)
                                step_interval = 0.06
                                # compute intended steps; allow small durations to still interpolate
                                steps = max(1, min(500, int(duration / step_interval)))
                                # if duration is short but non-zero, force at least 2 steps so
                                # 50% vs 100% aren't both collapsed into the same atomic write
                                if steps == 1 and duration > 0.03:
                                    steps = 2
                                if steps == 1:
                                    # atomic set for tiny/no-duration moves
                                    try:
                                        obj = self.servos[ch]["obj"]
                                        try:
                                            obj_name = type(obj).__name__
                                        except Exception:
                                            obj_name = str(obj)
                                        print(f"🖊️ [WRITE] Channel {ch} target={angle} obj={obj_name}")
                                        obj.angle = angle
                                    except Exception as e:
                                        print(f"❌ Fehler beim Schreiben auf Kanal {ch}: {e}")
                                else:
                                    sleep_per = duration / steps if steps > 0 else step_interval
                                    for i in range(1, steps + 1):
                                        interp = cur + (angle - cur) * (i / steps)
                                        try:
                                            # round to avoid tiny float jitter when servo expects ints
                                            obj = self.servos[ch]["obj"]
                                            try:
                                                obj_name = type(obj).__name__
                                            except Exception:
                                                obj_name = str(obj)
                                            val = round(interp, 2)
                                            print(f"🖊️ [WRITE] Channel {ch} interp={val} step={i}/{steps} obj={obj_name}")
                                            obj.angle = val
                                        except Exception as e:
                                            print(f"❌ Fehler beim schrittweisen Schreiben auf Kanal {ch}: {e}")
                                        time.sleep(sleep_per)
                                print(f"📡 Kanal {ch} → {angle}° (smooth over {duration:.2f}s, dps={dps:.1f})")
                            else:
                                # immediate set
                                try:
                                    obj = self.servos[ch]["obj"]
                                    try:
                                        obj_name = type(obj).__name__
                                    except Exception:
                                        obj_name = str(obj)
                                    print(f"🖊️ [WRITE] Channel {ch} immediate target={angle} obj={obj_name}")
                                    obj.angle = angle
                                except Exception as e:
                                    print(f"❌ Fehler beim Schreiben auf Kanal {ch}: {e}")
                            # remember last angle
                            self._last_angles[ch] = float(angle)
                        except Exception as e:
                            print(f"❌ Fehler beim Schreiben auf Kanal {ch}: {e}")
                    else:
                        # simulation mode: compute a realistic duration and sleep
                        if speed is not None:
                            try:
                                cur = self._last_angles.get(ch, float(angle))
                                deg = abs(angle - cur)
                                dps = _speed_to_dps(speed)
                                duration = max(0.0, deg / dps)
                                if duration > 0:
                                    time.sleep(duration)
                            except Exception:
                                pass
                        self._last_angles[ch] = float(angle)
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

    def move_servo(self, channel: int, angle: int, speed: int = None):
        try:
            ch = int(channel)
        except Exception:
            return
        if ch < 0 or ch > 15:
            return
        cmd = {"type": "move", "channel": ch, "angle": int(angle)}
        if speed is not None:
            try:
                cmd["speed"] = int(speed)
            except Exception:
                pass
        print(f"📥 Enqueue move command: channel={ch} angle={int(angle)} speed={cmd.get('speed')}")
        self.command_queue.put(cmd)

    def update_servo_pulse(self, channel: int, min_pulse: int, max_pulse: int) -> bool:
        """Update the min/max pulse for a servo channel at runtime.
        If hardware is available and the channel was initialized, recreate the
        `adafruit_motor.servo.Servo` object for that channel with new pulses.
        Returns True if applied, False otherwise.
        """
        try:
            ch = int(channel)
        except Exception:
            return False
        if not self.hardware_available:
            return False
        if ch not in self.servos or not self.servos.get(ch):
            return False
        try:
            # perform local imports to avoid module-level hardware deps
            from adafruit_motor import servo as adafruit_servo

            pca = self.servos[ch]["pca"]
            # construct new Servo with updated pulse limits
            new_s = adafruit_servo.Servo(pca.channels[ch], min_pulse=int(min_pulse), max_pulse=int(max_pulse))
            with self._lock:
                # replace servo object while preserving pca reference
                self.servos[ch]["obj"] = new_s
            print(f"🔧 Updated pulses for channel {ch}: min={min_pulse} max={max_pulse}")
            return True
        except Exception as e:
            print(f"❌ Failed to update pulses for channel {ch}: {e}")
            return False

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
