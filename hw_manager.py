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
        # per-channel active targets (used by set_target to avoid queue churn)
        self._targets: Dict[int, dict] = {}
        self._target_lock = threading.Lock()
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

    def _speed_to_dps(self, s, channel=None):
        """Convert a 1..100 speed value to degrees-per-second, using per-joint tuning if available."""
        try:
            s = int(s)
        except Exception:
            s = 50
        s = max(1, min(100, s))
        min_dps = 12.0
        max_dps = 360.0
        try:
            motion = self._load_calib_motion()
            if channel is not None and isinstance(self.channel_to_joint, dict):
                joint = self.channel_to_joint.get(channel)
                if joint and isinstance(motion, dict):
                    mj = motion.get(joint)
                    if isinstance(mj, dict):
                        if mj.get('min_dps') is not None:
                            min_dps = float(mj.get('min_dps'))
                        if mj.get('max_dps') is not None:
                            max_dps = float(mj.get('max_dps'))
        except Exception:
            pass
        ratio = max_dps / min_dps
        p = s / 100.0
        return min_dps * (ratio ** p)

    def _dps_from_mode(self, mode, channel=None):
        """Resolve a named mode ('slow'|'medium'|'fast') to a degrees-per-second value using calib motion.speed_modes if present.
        Falls back to using min_dps/max_dps mapping where medium maps to geometric mean.
        """
        try:
            if not mode:
                return None
            mode = str(mode).lower()
        except Exception:
            return None
        try:
            motion = self._load_calib_motion()
            if channel is not None and isinstance(self.channel_to_joint, dict):
                joint = self.channel_to_joint.get(channel)
                if joint and isinstance(motion, dict):
                    mj = motion.get(joint)
                    if isinstance(mj, dict):
                        sm = mj.get('speed_modes')
                        if isinstance(sm, dict) and sm.get(mode) is not None:
                            return float(sm.get(mode))
            # fallback: derive from min/max dps
            min_dps = 12.0
            max_dps = 360.0
            if isinstance(motion, dict) and channel is not None and isinstance(self.channel_to_joint, dict):
                joint = self.channel_to_joint.get(channel)
                if joint:
                    mj = motion.get(joint) or {}
                    if mj.get('min_dps') is not None:
                        min_dps = float(mj.get('min_dps'))
                    if mj.get('max_dps') is not None:
                        max_dps = float(mj.get('max_dps'))
            if mode == 'slow':
                return min_dps
            if mode == 'fast':
                return max_dps
            # medium: geometric mean for smooth interpolation
            return (min_dps * max_dps) ** 0.5
        except Exception:
            return None

    def _hardware_loop(self):
        print("🚀 Hardware-Thread startet...")
        if not self._init_hardware():
            print("⚠️ Hardware nicht verfügbar — laufe im Simulationsmodus")
        # time-based interpolation loop (avoid jitter by using small dt steps)
        last_ts = time.time()
        loop_sleep = 0.02  # 20ms base tick for smooth updates
        while self.running:
            try:
                # process at most one queued command per tick to keep responsiveness
                try:
                    cmd = self.command_queue.get_nowait()
                except queue.Empty:
                    cmd = None

                if cmd:
                    # basic command processing
                    try:
                        if cmd.get('type') == 'move':
                            ch = cmd.get('channel')
                            angle = int(cmd.get('angle'))
                            speed = cmd.get('speed')
                            speed_mode = cmd.get('speed_mode')
                            # if a newer target exists we prefer that
                            with self._target_lock:
                                if ch in self._targets:
                                    try:
                                        self.command_queue.task_done()
                                    except Exception:
                                        pass
                                    cmd = None
                                else:
                                    self.set_target(ch, angle, speed=speed, speed_mode=speed_mode)
                        elif cmd.get('type') == 'stop':
                            print('⛔ Not-Aus: setze alle Servos auf Home')
                            if self.hardware_available:
                                for ch in list(self.servos.keys()):
                                    if self.servos.get(ch):
                                        try:
                                            self.servos[ch]['obj'].angle = 90
                                        except Exception:
                                            pass
                            with self._lock:
                                try:
                                    while True:
                                        self.command_queue.get_nowait()
                                        self.command_queue.task_done()
                                except queue.Empty:
                                    pass
                    finally:
                        try:
                            self.command_queue.task_done()
                        except Exception:
                            pass

                # step active targets based on elapsed time
                now = time.time()
                dt = max(0.0, now - last_ts)
                last_ts = now
                with self._target_lock:
                    for ch, tgt in list(self._targets.items()):
                        try:
                            target = float(tgt.get('angle'))
                            # resolve dps from either numeric speed, mode, or per-joint defaults
                            dps = None
                            if tgt.get('speed_mode') is not None:
                                dps = self._dps_from_mode(tgt.get('speed_mode'), channel=ch)
                            if dps is None and tgt.get('speed') is not None:
                                dps = self._speed_to_dps(tgt.get('speed'), channel=ch)
                            if dps is None:
                                dps = self._speed_to_dps(50, channel=ch)

                            cur = self._last_angles.get(ch, target)
                            if abs(target - cur) < 0.5:
                                # reached target
                                self._last_angles[ch] = float(target)
                                if self.hardware_available and ch in self.servos and self.servos[ch]:
                                    try:
                                        self.servos[ch]['obj'].angle = round(target, 2)
                                    except Exception:
                                        pass
                                try:
                                    del self._targets[ch]
                                except Exception:
                                    pass
                                continue

                            # compute move amount based on dps and elapsed dt
                            # clamp by optional per-joint step_interval to avoid too-large jumps
                            move_delta = dps * dt
                            # check for configured max step interval (we keep move_delta as limit)
                            # apply move
                            delta = target - cur
                            step = max(-move_delta, min(move_delta, delta))
                            new_angle = cur + step
                            if self.hardware_available and ch in self.servos and self.servos[ch]:
                                try:
                                    self.servos[ch]['obj'].angle = round(new_angle, 2)
                                except Exception as e:
                                    print(f"❌ Fehler beim schrittweisen Schreiben auf Kanal {ch}: {e}")
                            self._last_angles[ch] = float(new_angle)
                        except Exception:
                            pass

                # sleep a short while to yield CPU and keep low-latency
                time.sleep(loop_sleep)
            except Exception as e:
                print(f"❌ Hardware-Thread Exception: {e}")

    def move_servo(self, channel: int, angle: int, speed: int = None, speed_mode: str = None):
        try:
            ch = int(channel)
        except Exception:
            return
        if ch < 0 or ch > 15:
            return
        # Use target-steering to avoid flooding the queue with intermediate moves
        try:
            self.set_target(ch, int(angle), speed=speed, speed_mode=speed_mode)
        except Exception:
            pass

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

    def set_target(self, channel: int, angle: float, speed: int = None, speed_mode: str = None):
        """Set an active target for a channel. The hardware thread will step toward this target.
        This replaces flooding the command queue with many moves and reduces churn.
        """
        try:
            ch = int(channel)
        except Exception:
            return False
        if ch < 0 or ch > 15:
            return False
        with self._target_lock:
            self._targets[ch] = {
                'angle': float(angle),
                'speed': int(speed) if speed is not None else None,
                'speed_mode': str(speed_mode) if speed_mode is not None else None,
                'ts': time.time()
            }
        print(f"📥 Set target: channel={ch} angle={angle} speed={speed} speed_mode={speed_mode}")
        return True

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
