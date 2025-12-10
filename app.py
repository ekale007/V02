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
_saved_lock = threading.Lock()

# Saved positions file
SAVED_FILE = os.path.join(ROOT, "saved_positions.json")

def load_saved_positions():
    if os.path.exists(SAVED_FILE):
        try:
            with open(SAVED_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print('⚠️ Could not read saved_positions.json:', e)
            return []
    return []

def save_saved_positions(arr):
    tmp = SAVED_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(arr, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SAVED_FILE)

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

# --- Arm presets persistence ---
ARMS_DIR = os.path.join(ROOT, 'arms')
if not os.path.exists(ARMS_DIR):
    try:
        os.makedirs(ARMS_DIR, exist_ok=True)
    except Exception:
        pass

def list_arms():
    try:
        files = [f for f in os.listdir(ARMS_DIR) if f.endswith('.json')]
        return [os.path.splitext(f)[0] for f in files]
    except Exception:
        return []

def load_arm(name):
    path = os.path.join(ARMS_DIR, name + '.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def save_arm(name, data):
    path = os.path.join(ARMS_DIR, name + '.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# --- Calibration storage (simple defaults) ---
def default_calib():
    limits = { j: [0, 180] for j in cfg.SERVO_MAP.keys() }
    home = dict(cfg.CURRENT_POSITIONS)
    step = { j: 5 for j in cfg.SERVO_MAP.keys() }
    pulse = { j: {"min_pulse": 500, "max_pulse": 2500} for j in cfg.SERVO_MAP.keys() }
    return {"limits": limits, "home": home, "step": step, "pulse": pulse, "reverse": { j: False for j in cfg.SERVO_MAP.keys() }}

def load_calib():
    if os.path.exists(CALIB_FILE):
        try:
            with open(CALIB_FILE, "r", encoding="utf-8") as f:
                c = json.load(f)
            # ensure reverse map exists for backward compatibility
            if 'reverse' not in c or not isinstance(c.get('reverse'), dict):
                c['reverse'] = { j: False for j in cfg.SERVO_MAP.keys() }
            else:
                # ensure all known joints are present
                for j in cfg.SERVO_MAP.keys():
                    if j not in c['reverse']:
                        c['reverse'][j] = False
            return c
        except Exception as e:
            print("⚠️ Konnte calib.json nicht lesen:", e)
            return default_calib()
    # ensure older installs get a reverse map
    c = default_calib()
    if 'reverse' not in c:
        c['reverse'] = { j: False for j in cfg.SERVO_MAP.keys() }
    return c

def save_calib(calib):
    tmp = CALIB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CALIB_FILE)

CALIB = load_calib()

# Helper: map between UI/display angle and physical servo angle using per-joint limits
def _apply_reverse_mapping_to_server(joint, ui_angle):
    """Convert a UI/display angle into the physical servo angle stored on the server.
    If the joint is marked as reversed in CALIB['reverse'], mirror within limits.
    """
    try:
        lo, hi = CALIB.get('limits', {}).get(joint, [0, 180])
        rev = CALIB.get('reverse', {}).get(joint, False)
        a = int(ui_angle)
        if rev:
            return int(lo + hi - a)
        return int(a)
    except Exception:
        try:
            return int(ui_angle)
        except Exception:
            return 0

def _map_server_to_ui(joint, server_angle):
    """Convert stored server physical angle into UI/display angle respecting reverse flag."""
    try:
        lo, hi = CALIB.get('limits', {}).get(joint, [0, 180])
        rev = CALIB.get('reverse', {}).get(joint, False)
        a = int(server_angle)
        if rev:
            return int(lo + hi - a)
        return int(a)
    except Exception:
        try:
            return int(server_angle)
        except Exception:
            return 0

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


@app.route('/block_arm')
def block_arm():
    # lightweight block-arm demo page (Three.js)
    return render_template('block_arm.html')

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


# --- Arm presets API ---
@app.route('/api/arms', methods=['GET'])
def api_arms_list():
    try:
        names = list_arms()
        return jsonify({'arms': names})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arms/<name>', methods=['GET'])
def api_arms_get(name):
    try:
        arm = load_arm(name)
        if arm is None:
            return jsonify({'error': 'not found'}), 404
        return jsonify(arm)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arms', methods=['POST'])
def api_arms_post():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'missing json'}), 400
    name = data.get('name')
    cfg_data = data.get('config')
    if not name or not isinstance(name, str):
        return jsonify({'error': 'missing name'}), 400
    if not cfg_data or not isinstance(cfg_data, dict):
        return jsonify({'error': 'missing config object'}), 400
    try:
        save_arm(name, cfg_data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Status & control endpoints ---
@app.route('/api/status', methods=['GET'])
def api_status():
    # Expose positions mapped into UI/display space (respect reverse flags)
    mapped = {}
    for j in cfg.SERVO_MAP.keys():
        server_ang = cfg.CURRENT_POSITIONS.get(j, 0)
        mapped[j] = _map_server_to_ui(j, server_ang)
    return jsonify({
        'hardware_available': servo_manager.hardware_available,
        'positions': mapped
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
    speed_mode = None
    try:
        if 'speed' in data:
            speed = int(data.get('speed'))
        if 'speed_mode' in data:
            speed_mode = data.get('speed_mode')
    except Exception:
        speed = None
    # Apply server-side reverse mapping before enqueuing hardware move
    server_angle = _apply_reverse_mapping_to_server(joint, angle)
    # If no explicit speed provided, use a sensible default to enable smoothing
    if speed is None:
        speed = 45
    # Pass either numeric speed or named speed_mode to the hardware manager
    try:
        if speed_mode is not None:
            servo_manager.move_servo(ch, server_angle, speed=speed, speed_mode=speed_mode)
        else:
            servo_manager.move_servo(ch, server_angle, speed=speed)
    except Exception:
        servo_manager.move_servo(ch, server_angle, speed=speed)
    # store last-known physical servo angle on server
    cfg.CURRENT_POSITIONS[joint] = int(server_angle)
    return jsonify({'success': True, 'joint': joint, 'angle': angle, 'server_angle': server_angle})


@app.route('/api/set_target', methods=['POST'])
def api_set_target():
    """Set a persistent target on the server/hardware thread (avoids queue churn).
    Accepts JSON: { "joint": "shoulder" | "channel": 3, "angle": 90, "speed": 50 }
    """
    req = request.get_json(silent=True)
    if not req:
        return jsonify(error='missing json'), 400
    angle = req.get('angle')
    if angle is None:
        return jsonify(error='missing angle'), 400
    speed = req.get('speed')
    # prefer joint name if given
    channel = None
    if 'joint' in req:
        joint = req.get('joint')
        channel = cfg.SERVO_MAP.get(joint)
        if channel is None:
            return jsonify(error='unknown joint'), 400
    elif 'channel' in req:
        try:
            channel = int(req.get('channel'))
        except Exception:
            return jsonify(error='invalid channel'), 400
    else:
        return jsonify(error='missing joint or channel'), 400

    try:
        angle = int(angle)
    except Exception:
        return jsonify(error='invalid angle'), 400

    speed_mode = req.get('speed_mode') if 'speed_mode' in req else None

    ok = servo_manager.set_target(channel, angle, speed=speed, speed_mode=speed_mode)
    if not ok:
        return jsonify(error='failed to set target'), 500
    return jsonify(success=True)

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
    # set home positions from calibration (server-side) if present
    for j,ch in cfg.SERVO_MAP.items():
        try:
            h_ui = CALIB.get('home', {}).get(j, (0 if j == 'hand' else 90))
            server_h = _apply_reverse_mapping_to_server(j, h_ui)
        except Exception:
            server_h = 0 if j == 'hand' else 90
        servo_manager.move_servo(ch, server_h)
        cfg.CURRENT_POSITIONS[j] = int(server_h)
    # return positions mapped into UI space
    mapped = { j: _map_server_to_ui(j, cfg.CURRENT_POSITIONS.get(j, 0)) for j in cfg.SERVO_MAP.keys() }
    return jsonify({'success': True, 'positions': mapped})

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
    # Read JSON body for calibration updates
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
        # optional reverse flag (bool)
        try:
            if 'reverse' in data:
                if 'reverse' not in CALIB or not isinstance(CALIB['reverse'], dict):
                    CALIB['reverse'] = {}
                CALIB['reverse'][joint] = bool(data.get('reverse'))
        except Exception:
            pass

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

        # motion tuning fields (optional): store per-joint min_dps/max_dps and step_interval
        try:
            min_dps = data.get('min_dps')
            max_dps = data.get('max_dps')
            step_interval = data.get('step_interval')
            # speed mode shortcuts: clients can send explicit values for slow/medium/fast
            speed_modes = data.get('speed_modes')
            speed_slow = data.get('speed_slow')
            speed_medium = data.get('speed_medium')
            speed_fast = data.get('speed_fast')
            # Accept step_interval even if min_dps/max_dps are not provided
            if min_dps is not None or max_dps is not None or step_interval is not None:
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
                # optional step_interval (seconds per hardware step)
                if step_interval is not None:
                    try:
                        CALIB['motion'][joint]['step_interval'] = float(step_interval)
                    except Exception:
                        pass
            # persist speed_modes if provided (either nested or individual fields)
                if speed_modes is not None or speed_slow is not None or speed_medium is not None or speed_fast is not None:
                    if 'motion' not in CALIB or not isinstance(CALIB['motion'], dict):
                        CALIB['motion'] = {}
                    if joint not in CALIB['motion'] or not isinstance(CALIB['motion'][joint], dict):
                        CALIB['motion'][joint] = {}
                    sm = CALIB['motion'][joint].get('speed_modes') or {}
                    if isinstance(speed_modes, dict):
                        for k, v in speed_modes.items():
                            try:
                                sm[str(k).lower()] = float(v)
                            except Exception:
                                pass
                    if speed_slow is not None:
                        try: sm['slow'] = float(speed_slow)
                        except Exception: pass
                    if speed_medium is not None:
                        try: sm['medium'] = float(speed_medium)
                        except Exception: pass
                    if speed_fast is not None:
                        try: sm['fast'] = float(speed_fast)
                        except Exception: pass
                    CALIB['motion'][joint]['speed_modes'] = sm
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
    server_angle = _apply_reverse_mapping_to_server(joint, angle)
    if speed is None:
        speed = 45
    servo_manager.move_servo(ch, server_angle, speed=speed)
    cfg.CURRENT_POSITIONS[joint] = int(server_angle)
    return jsonify({'success': True, 'server_angle': server_angle})


# --- Saved positions (persisted server-side) ---
@app.route('/api/saved_positions', methods=['GET'])
def api_saved_positions_get():
    try:
        with _saved_lock:
            arr = load_saved_positions() or []
        return jsonify({'saved': arr})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved_positions', methods=['POST'])
def api_saved_positions_post():
    data = request.get_json() or {}
    name = data.get('name')
    positions = data.get('positions')
    if not name or not isinstance(name, str):
        return jsonify({'error': 'missing name'}), 400
    if not positions or not isinstance(positions, dict):
        return jsonify({'error': 'missing positions'}), 400
    try:
        with _saved_lock:
            arr = load_saved_positions() or []
            # upsert
            idx = next((i for i,v in enumerate(arr) if v.get('name')==name), None)
            item = {'name': name, 'positions': positions, 'ts': int(time.time()*1000)}
            if idx is None:
                arr.append(item)
            else:
                arr[idx] = item
            save_saved_positions(arr)
        return jsonify({'success': True, 'saved': item})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved_positions', methods=['DELETE'])
def api_saved_positions_delete():
    data = request.get_json() or {}
    name = data.get('name')
    if not name or not isinstance(name, str):
        return jsonify({'error': 'missing name'}), 400
    try:
        with _saved_lock:
            arr = load_saved_positions() or []
            arr = [v for v in arr if v.get('name') != name]
            save_saved_positions(arr)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved_positions/export', methods=['GET'])
def api_saved_positions_export():
    """Return saved positions as a downloadable JSON file."""
    try:
        with _saved_lock:
            arr = load_saved_positions() or []
        content = json.dumps({'saved': arr}, indent=2, ensure_ascii=False)
        # Use a Response with attachment headers so browsers download the file
        from flask import Response
        resp = Response(content, mimetype='application/json')
        resp.headers['Content-Disposition'] = 'attachment; filename=saved_positions_export.json'
        return resp
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved_positions/import', methods=['POST'])
def api_saved_positions_import():
    """Import saved positions. Accepts JSON body of form { saved: [ {name, positions, ts?}, ... ] }
    If `replace` query param is truthy, replace existing list; otherwise merge by name (upsert).
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'missing json body'}), 400
        incoming = data.get('saved') if isinstance(data.get('saved'), list) else (data if isinstance(data, list) else None)
        if incoming is None:
            return jsonify({'error': 'invalid payload, expected list under `saved` or a top-level array'}), 400
        replace = request.args.get('replace') in ('1', 'true', 'yes')
        # validate items
        clean = []
        for it in incoming:
            if not it or not isinstance(it, dict):
                continue
            name = it.get('name')
            pos = it.get('positions')
            if not name or not isinstance(name, str) or not pos or not isinstance(pos, dict):
                continue
            clean.append({'name': name, 'positions': pos, 'ts': int(time.time()*1000)})
        if not clean:
            return jsonify({'error': 'no valid entries found'}), 400
        with _saved_lock:
            existing = load_saved_positions() or []
            if replace:
                final = clean
            else:
                # merge by name (upsert)
                byname = { v.get('name'): v for v in existing }
                for it in clean:
                    byname[it['name']] = it
                final = list(byname.values())
            save_saved_positions(final)
        return jsonify({'success': True, 'imported': len(clean)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
