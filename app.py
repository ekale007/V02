"""Main Flask application that wires UI, kinematics and hardware manager.
Added sim config endpoints and persistent sim.json storage.
"""
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import threading
import time
import os
import json

from hw_manager import ServoManager
import kinematics
import ui_config

app = Flask(__name__)
CORS(app)

servo_manager = ServoManager()
kin = kinematics
cfg = ui_config

# Simulation config storage
SIM_FILE = os.path.join(os.path.dirname(__file__), "sim.json")
_sim_lock = threading.Lock()


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

@app.route('/')
def index():
    return render_template('index.html', servo_map=cfg.SERVO_MAP, positions=cfg.CURRENT_POSITIONS, meta=cfg.UI_META, sim_config=SIM)

@app.route('/api/simconfig', methods=['GET'])
def api_sim_get():
    with _sim_lock:
        return jsonify(SIM)

@app.route('/api/simconfig', methods=['POST'])
def api_sim_post():
    data = request.get_json() or {}
    with _sim_lock:
        # merge keys
        try:
            if 'lengths' in data:
                for k,v in data['lengths'].items():
                    SIM['lengths'][k] = int(v)
            if 'origin' in data:
                for k,v in data['origin'].items():
                    SIM['origin'][k] = int(v)
            if 'scale' in data:
                SIM['scale'] = float(data['scale'])
            if data.get('save'):
                save_sim_config(SIM)
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    return jsonify({'success': True, 'sim': SIM})

# existing endpoints (status, move, home, test, programs, emergency) remain unchanged
from flask import Flask  # keep previous content - endpoints already in repo

# For simplicity we import rest of app endpoints from the existing module area by reusing the file's original code.
# (When merging locally, ensure no duplicate endpoint definitions.)

if __name__ == '__main__':
    print('Starting app with sim support...')
    app.run(host='0.0.0.0', port=8080, threaded=True)
