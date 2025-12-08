<!-- .github/copilot-instructions.md -->
# Robot Arm — AI Agent Instructions

Short: actionable guidance to help an AI coding agent be productive in this repository.

Overview
- Main components: `app.py` (Flask API + UI wiring), `hw_manager.py` (ServoManager background thread and queue),
  `kinematics.py` (joint names, clamps, program sequences), `ui_config.py` (SERVO_MAP, defaults), `templates/index.html` (single-page UI + JS).
- Runtime data files: `calib.json` and `sim.json` (created by `scripts/install.sh` if missing).

How to run (quick)
- Create venv and install: `python3 -m venv venv; source venv/bin/activate; pip install -r requirements.txt`.
- Run server (simulation if hardware libs missing): `python3 app.py` — listens on `0.0.0.0:8080`.
- Installer: `sudo ./scripts/install.sh` (options: `--user`, `--venv-dir`, `--no-systemd`, `--yes`).

Key patterns and project conventions
- Joint names are canonical strings used across modules: e.g., `base`, `shoulder`, `elbow`, `wrist`, `hand`.
  - Update `ui_config.SERVO_MAP`, `kinematics.JOINTS` and `calib.json` together when adding/removing joints.
- `ui_config.SERVO_MAP` maps logical joint → PCA9685 channel. The template iterates `servo_map` to build sliders.
- `ServoManager` runs a hardware thread and intentionally performs hardware imports (`board`, `busio`, `adafruit_*`) inside
  `_init_hardware()` — this keeps imports safe on developer machines without hardware. If init fails the manager runs in simulation mode.
- The UI uses fetch() to call server endpoints (`/api/move`, `/api/status`, `/api/calibration`, `/api/simconfig`). See `templates/index.html` for concrete request/response examples.
- Calibration and pulse widths: `calib.json` stores `limits`, `home`, `step`, and optional `pulse` per joint. Pulse overrides are loaded by `ServoManager._load_calib_pulses()`.

Common change patterns (examples)
- Add a new joint:
  1. Add key in `ui_config.SERVO_MAP` with channel number.
  2. Add joint name to `kinematics.JOINTS` and update `_LIMITS`/_HOME as needed.
  3. Update `calib.json` (limits/home/step) and optionally `sim.json` lengths.
  4. The UI will pick up new joint automatically because `templates/index.html` loops `servo_map`.
- Change pulse mapping: update `calib.json` under `pulse` for joint-specific `min_pulse`/`max_pulse`.

Developer workflows & gotchas
- Tests: there are no automated tests in the repo. Validate changes by running the app and using the UI (`/`).
- Hardware vs simulation: on non-RPi machines the Adafruit hardware libs will be missing — this is expected. Use simulation (ServoManager will set `hardware_available=False`).
- Concurrency: the app uses background threads for programs and the hardware loop. Keep long-running or blocking work off the Flask main thread.
- Persistence: `app.py` reads/writes `calib.json` and `sim.json` from repository root (atomic write via `*.tmp` → `replace()`).
- Security: there is no authentication; only run on trusted networks or behind VPN.

Where to look for examples
- UI endpoint usage and polling: `templates/index.html` (inline JS shows payload shapes and polling cadence `poll()`).
- Background/hardware queue pattern: `hw_manager.py` (command queue, `move_servo()`, `emergency_stop()` behavior).
- Prebuilt sequences & clamps: `kinematics.py` (`wave_sequence`, `pickplace_sequence`, `clamp_angle`).
- Installer and service: `scripts/install.sh` and `robot-arm.service` (how it expects venv and ExecStart path).

If something is unclear
- Ask the repo owner for runtime details (I2C address, number of channels used) or provide a small failing example and I will read and adapt instructions.

Keep edits minimal and focused: prefer updating `ui_config.py` and `calib.json` for configuration changes rather than editing template markup unless UI behavior needs to change.

Concrete examples
 - Example `POST /api/move` payload (move a joint):
   ```json
   { "joint": "shoulder", "angle": 75 }
   ```
   - Server action: validates `joint` against `ui_config.SERVO_MAP`, converts `angle` to int, then calls `ServoManager.move_servo(channel, angle)` and updates `ui_config.CURRENT_POSITIONS`.

 - Example `POST /api/calibration/update` payload (apply limits, optional save and pulse overrides):
   ```json
   {
     "joint": "elbow",
     "min": 10,
     "max": 170,
     "step": 5,
     "home": 90,
     "pulse_min": 520,
     "pulse_max": 2480,
     "save": true
   }
   ```
   - Server action: updates `CALIB` in memory, applies pulse fields into `CALIB['pulse'][joint]` when provided, and saves to `calib.json` if `save` is true.

 - Example `POST /api/calibration/move` payload (move servo during calibration):
   ```json
   { "joint": "hand", "angle": 40 }
   ```
   - Server action: validates joint, calls `servo_manager.move_servo()` and updates `ui_config.CURRENT_POSITIONS`.

 - Example `POST /api/simconfig` payload (update simulation lengths & scale):
   ```json
   {
     "lengths": {"shoulder": 95, "elbow": 72, "wrist": 52, "hand": 22},
     "scale": 1.05,
     "save": true
   }
   ```
   - Server action: applies fields to the `SIM` dict and persists to `sim.json` when `save` is present and truthy.

 - Programs are started via POST endpoints (no body):
   - `POST /api/program/wave` — starts the wave program in a background thread.
   - `POST /api/program/pickplace` — starts pick & place sequence in background.

Sample `calib.json` snippet
 - Typical `calib.json` layout produced by `scripts/install.sh` and used by `ServoManager`:
   ```json
   {
     "limits": {
       "base": [0, 180],
       "shoulder": [15, 165],
       "elbow": [0, 180],
       "wrist": [0, 180],
       "hand": [0, 90]
     },
     "home": {
       "base": 90,
       "shoulder": 90,
       "elbow": 90,
       "wrist": 90,
       "hand": 0
     },
     "step": {
       "base": 5,
       "shoulder": 5,
       "elbow": 5,
       "wrist": 5,
       "hand": 5
     },
     "pulse": {
       "base": { "min_pulse": 500, "max_pulse": 2500 },
       "hand": { "min_pulse": 520, "max_pulse": 2400 }
     }
   }
   ```
 - Notes:
   - `limits` entries must match keys in `ui_config.SERVO_MAP`.
   - `pulse` entries are optional; when present `ServoManager._init_hardware()` will use those `min_pulse` / `max_pulse` values for the `adafruit_motor.servo.Servo` constructor.

