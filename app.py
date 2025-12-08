#!/usr/bin/env python3
"""Main Flask application that wires UI, kinematics and hardware manager.
Contains API endpoints for UI control, status and simple programs.
"""
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import threading
import time
import os
import json

from hw_manager import ServoManager
import kinematics
import ui_config as cfg

app = Flask(__name__)
CORS(app)

servo_manager = ServoManager()

# Paths
ROOT = os.path.dirname(__file__)
SIM_FILE = os.path.join(ROOT, "sim.json")
CALIB_FILE = os.path.join(ROOT, "calib.json")
_sim_lock = threading.Lock()
_calib_lock = threading.Lock()

# --- Sim config helpers ---
def load_sim_config():
    if os.path.exists(SIM_FILE):
        try:
            with open(SIM_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"⚠️ Konnte sim.json nicht lesen ({e}), verwende Defaults")
            return cfg.SIM_CONFIG
    return cfg.SIM_CONFIG

def save_sim_config(sim):
    tmp = SIM_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sim, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SIM_FILE)

SIM = load_sim_config()

# --- Calibration storage (simple defaults) ---
def default_calib():
    limits = { j: [0, 180] for j in cfg.SERVO_MAP.keys() }
    home = dict(cfg.CURRENT_POSITIONS)
    step = { j: 5 for j in cfg.SERVO_MAP.keys() }
    pulse = { j: {"min_pulse": 500, "max_pulse": 2500} for j in cfg.SERVO_MAP.keys() }
    return {"limits": limits, "home": home, "step": step, "pulse": pulse}

def load_calib():
    if os.path.exists(CALIB_FILE):
        try:
            with open(CALIB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("⚠️ Konnte calib.json nicht lesen:", e)
            return default_calib()
    return default_calib()

def save_calib(calib):
    tmp = CALIB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CALIB_FILE)

CALIB = load_calib()

# --- Web UI ---
@app.route('/')
def index():
    # Serve the full 3D interactive editor as the new index page.
    # Keep the /3d route as-is for explicit access.
    return render_template('sim3d.html')

@app.route('/3d')
def sim3d():
    # simple 3D interactive simulation page
    return render_template('sim3d.html')

# --- Sim config endpoints ---
@app.route('/api/simconfig', methods=['GET'])
def api_sim_get():
    with _sim_lock:
        return jsonify(SIM)

@app.route('/api/simconfig', methods=['POST'])
def api_sim_post():
    data = request.get_json() or {}
    with _sim_lock:
        try:
            if 'lengths' in data:
                for k,v in data['lengths'].items():
                    SIM['lengths'][k] = int(v)
            if 'origin' in data:
                for k,v in data['origin'].items():
                    SIM['origin'][k] = int(v)
            # axes mapping: allow updating which axis each joint rotates around
            if 'axes' in data and isinstance(data['axes'], dict):
                if 'axes' not in SIM or not isinstance(SIM['axes'], dict):
                    SIM['axes'] = {}
                for k,v in data['axes'].items():
                    SIM['axes'][k] = str(v)
            # offsets mapping: allow updating angle offsets for joints (degrees)
            if 'offsets' in data and isinstance(data['offsets'], dict):
                if 'offsets' not in SIM or not isinstance(SIM['offsets'], dict):
                    SIM['offsets'] = {}
                for k, v in data['offsets'].items():
                    # Accept either a scalar legacy offset or a nested object {a,b,c}
                    try:
                        if isinstance(v, dict):
                            # Coerce values to numbers (float) for a/b/c
                            a = v.get('a', 0)
                            b = v.get('b', 0)
                            c = v.get('c', 0)
                            try:
                                a = float(a)
                            except Exception:
                                a = 0.0
                            try:
                                b = float(b)
                            except Exception:
                                b = 0.0
                            try:
                                c = float(c)
                            except Exception:
                                c = 0.0
                            SIM['offsets'][k] = {'a': a, 'b': b, 'c': c}
                        else:
                            # scalar offset (legacy) — store as integer for backward compat
                            SIM['offsets'][k] = int(v)
                    except Exception:
                        SIM['offsets'][k] = v if isinstance(v, dict) else 0
            if 'scale' in data:
                SIM['scale'] = float(data['scale'])
            if data.get('save'):
                save_sim_config(SIM)
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    return jsonify({'success': True, 'sim': SIM})

# --- Status & control endpoints ---
@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        'hardware_available': servo_manager.hardware_available,
        'positions': cfg.CURRENT_POSITIONS
    })

@app.route('/api/move', methods=['POST'])
def api_move():
    # Use robust parsing of JSON body to avoid Werkzeug BadRequest on malformed content-type
    try:
        raw = request.get_data(as_text=True) or '{}'
        print(f"🔍 Raw request body: {raw!r}")
        data = json.loads(raw)
    except Exception as e:
        print(f"⚠️ Failed to parse JSON body: {e}")
        data = {}
    joint = data.get('joint')
    angle = data.get('angle')
    print(f"🔔 Received move request: joint={joint} angle={angle}")
    if joint not in cfg.SERVO_MAP:
        return jsonify({'error': 'unknown joint'}), 400
    try:
        angle = int(angle)
    except Exception:
        return jsonify({'error': 'invalid angle'}), 400
    ch = cfg.SERVO_MAP[joint]
    # optional speed field from client (1..100)
    speed = None
    try:
        if 'speed' in data:
            speed = int(data.get('speed'))
    except Exception:
        speed = None
    servo_manager.move_servo(ch, angle, speed=speed)
    # update current positions
    cfg.CURRENT_POSITIONS[joint] = angle
    return jsonify({'success': True, 'joint': joint, 'angle': angle})

@app.route('/api/test/<joint>', methods=['POST'])
def api_test(joint):
    if joint not in cfg.SERVO_MAP:
        return jsonify({'error': 'unknown joint'}), 400
    ch = cfg.SERVO_MAP[joint]
    # simple test: sweep 60 -> 120 -> home
    def seq():
        for a in (60, 120, cfg.CURRENT_POSITIONS.get(joint, 90)):
            servo_manager.move_servo(ch, a)
            # small delay between commands so hardware thread processes them
            time.sleep(0.6)
    threading.Thread(target=seq, daemon=True).start()
    return jsonify({'success': True})

@app.route('/api/home', methods=['POST'])
def api_home():
    # set "home" positions: hand->0, others->90 (same as UI)
    for j,ch in cfg.SERVO_MAP.items():
        h = 0 if j == 'hand' else 90
        servo_manager.move_servo(ch, h)
        cfg.CURRENT_POSITIONS[j] = h
    return jsonify({'success': True, 'positions': cfg.CURRENT_POSITIONS})

@app.route('/api/emergency', methods=['POST'])
def api_emergency():
    servo_manager.emergency_stop()
    return jsonify({'success': True})

# --- calibration endpoints used by UI ---
@app.route('/api/calibration', methods=['GET'])
def api_calibration_get():
    return jsonify(CALIB)

@app.route('/api/calibration/update', methods=['POST'])
def api_calibration_update():
    data = request.get_json() or {}
    joint = data.get('joint')
    if joint not in CALIB['limits']:
        return jsonify({'error': 'unknown joint'}), 400
    try:
        lo = int(data.get('min'))
        hi = int(data.get('max'))
        step = int(data.get('step'))
        home = int(data.get('home'))
    except Exception:
        return jsonify({'error': 'invalid values'}), 400
    with _calib_lock:
        CALIB['limits'][joint] = [lo, hi]
        CALIB['step'][joint] = step
        CALIB['home'][joint] = home

        # pulse fields (optional)
        try:
            pmin = data.get('pulse_min')
            pmax = data.get('pulse_max')
            if pmin is not None or pmax is not None:
                # ensure pulse mapping exists
                if 'pulse' not in CALIB:
                    CALIB['pulse'] = {}
                if joint not in CALIB['pulse'] or not isinstance(CALIB['pulse'][joint], dict):
                    CALIB['pulse'][joint] = {"min_pulse": 500, "max_pulse": 2500}
                if pmin is not None:
                    CALIB['pulse'][joint]['min_pulse'] = int(pmin)
                if pmax is not None:
                    CALIB['pulse'][joint]['max_pulse'] = int(pmax)
                # Apply pulses to running hardware if possible
                try:
                    ch = cfg.SERVO_MAP.get(joint)
                    if ch is not None:
                        servo_manager.update_servo_pulse(ch, CALIB['pulse'][joint]['min_pulse'], CALIB['pulse'][joint]['max_pulse'])
                except Exception as e:
                    print("⚠️ Fehler beim Anwenden der Pulseinstellungen (runtime):", e)
        except Exception as e:
            print("⚠️ Fehler beim Anwenden der Pulseinstellungen:", e)

        # motion tuning fields (optional): store per-joint min_dps/max_dps
        try:
            min_dps = data.get('min_dps')
            max_dps = data.get('max_dps')
            if min_dps is not None or max_dps is not None:
                if 'motion' not in CALIB or not isinstance(CALIB['motion'], dict):
                    CALIB['motion'] = {}
                if joint not in CALIB['motion'] or not isinstance(CALIB['motion'][joint], dict):
                    CALIB['motion'][joint] = {}
                if min_dps is not None:
                    try:
                        CALIB['motion'][joint]['min_dps'] = float(min_dps)
                    except Exception:
                        pass
                if max_dps is not None:
                    try:
                        CALIB['motion'][joint]['max_dps'] = float(max_dps)
                    except Exception:
                        pass
                # persist now if requested
                if data.get('save'):
                    try:
                        save_calib(CALIB)
                    except Exception as e:
                        print("⚠️ Fehler beim Speichern der Kalibrierung (motion):", e)
        except Exception as e:
            print("⚠️ Fehler beim Anwenden der Motion-Einstellungen:", e)

        if data.get('save'):
            try:
                save_calib(CALIB)
            except Exception as e:
                print("⚠️ Fehler beim Speichern der Kalibrierung:", e)
    return jsonify({'success': True})

@app.route('/api/calibration/save', methods=['POST'])
def api_calibration_save():
    try:
        save_calib(CALIB)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/calibration/move', methods=['POST'])
def api_calibration_move():
    data = request.get_json() or {}
    joint = data.get('joint')
    try:
        angle = int(data.get('angle'))
    except Exception:
        return jsonify({'error': 'invalid angle'}), 400
    if joint not in cfg.SERVO_MAP:
        return jsonify({'error': 'unknown joint'}), 400
    ch = cfg.SERVO_MAP[joint]
    speed = None
    try:
        if 'speed' in data:
            speed = int(data.get('speed'))
    except Exception:
        speed = None
    servo_manager.move_servo(ch, angle, speed=speed)
    cfg.CURRENT_POSITIONS[joint] = angle
    return jsonify({'success': True})

# --- simple programs (background threads) ---
@app.route('/api/program/wave', methods=['POST'])
def api_program_wave():
    # wave using wrist/hand
    def prog():
        for _ in range(4):
            servo_manager.move_servo(cfg.SERVO_MAP.get('wrist', 3), 50)
            time.sleep(0.4)
            servo_manager.move_servo(cfg.SERVO_MAP.get('wrist', 3), 130)
            time.sleep(0.4)
        # back to home for wrist
        servo_manager.move_servo(cfg.SERVO_MAP.get('wrist', 3), cfg.CURRENT_POSITIONS.get('wrist', 90))
    threading.Thread(target=prog, daemon=True).start()
    return jsonify({'started': True})

@app.route('/api/program/pickplace', methods=['POST'])
def api_program_pickplace():
    def prog():
        # very simple pick & place sequence (positions are example values)
        seq = [
            ('shoulder', 70), ('elbow', 110), ('wrist', 100), ('hand', 10),
            ('hand', 60),
            ('shoulder', 90), ('elbow', 90), ('wrist', 90), ('hand', 0)
        ]
        for joint, angle in seq:
            ch = cfg.SERVO_MAP.get(joint)
            if ch is not None:
                servo_manager.move_servo(ch, angle)
                cfg.CURRENT_POSITIONS[joint] = angle
            time.sleep(0.6)
    threading.Thread(target=prog, daemon=True).start()
    return jsonify({'started': True})

if __name__ == '__main__':
    print('Starting app with sim + control endpoints...')
    app.run(host='0.0.0.0', port=8080, threaded=True)
