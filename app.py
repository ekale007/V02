"""Main Flask application that wires UI, kinematics and hardware manager.
"""
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import threading
import time

from hw_manager import ServoManager
import kinematics
import ui_config

app = Flask(__name__)
CORS(app)

servo_manager = ServoManager()
kin = kinematics
cfg = ui_config

@app.route('/')
def index():
    return render_template('index.html', servo_map=cfg.SERVO_MAP, positions=cfg.CURRENT_POSITIONS, meta=cfg.UI_META)

@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        'positions': cfg.CURRENT_POSITIONS,
        'hardware_available': servo_manager.hardware_available
    })

@app.route('/api/move', methods=['POST'])
def api_move():
    data = request.get_json() or {}
    joint = data.get('joint')
    angle = data.get('angle')
    if joint not in cfg.SERVO_MAP:
        return jsonify({'error': 'Invalid joint'}), 400
    try:
        angle = int(angle)
    except Exception:
        return jsonify({'error': 'Angle must be integer'}), 400
    # clamp using kinematics limits
    angle = kin.clamp_angle(joint, angle)

    cfg.CURRENT_POSITIONS[joint] = angle
    servo_manager.move_servo(cfg.SERVO_MAP[joint], angle)
    return jsonify({'success': True, 'joint': joint, 'angle': angle})

@app.route('/api/home', methods=['POST'])
def api_home():
    home = kin.get_home_positions()
    for j, a in home.items():
        cfg.CURRENT_POSITIONS[j] = a
        servo_manager.move_servo(cfg.SERVO_MAP[j], a)
        time.sleep(0.03)
    return jsonify({'success': True})

@app.route('/api/test/<joint>', methods=['POST'])
def api_test(joint):
    if joint not in cfg.SERVO_MAP:
        return jsonify({'error': 'Invalid joint'}), 400
    def seq():
        for a in [0, 90, 180, 90]:
            if joint == 'hand' and a > 90:
                a = 90
            a = kin.clamp_angle(joint, a)
            cfg.CURRENT_POSITIONS[joint] = a
            servo_manager.move_servo(cfg.SERVO_MAP[joint], a)
            time.sleep(0.8)
    t = threading.Thread(target=seq, daemon=True)
    t.start()
    return jsonify({'success': True})

@app.route('/api/program/wave', methods=['POST'])
def api_wave():
    steps = kin.wave_sequence()
    def run():
        for s in steps:
            pos = s.get('positions', {})
            for j, a in pos.items():
                a = kin.clamp_angle(j, a)
                cfg.CURRENT_POSITIONS[j] = a
                servo_manager.move_servo(cfg.SERVO_MAP[j], a)
            time.sleep(s.get('delay', 0.5))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'success': True})

@app.route('/api/program/pickplace', methods=['POST'])
def api_pickplace():
    steps = kin.pickplace_sequence()
    def run():
        for s in steps:
            pos = s.get('positions', {})
            for j, a in pos.items():
                a = kin.clamp_angle(j, a)
                cfg.CURRENT_POSITIONS[j] = a
                servo_manager.move_servo(cfg.SERVO_MAP[j], a)
            time.sleep(s.get('delay', 0.5))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'success': True})

@app.route('/api/emergency', methods=['POST'])
def api_emergency():
    servo_manager.emergency_stop()
    for j in cfg.SERVO_MAP:
        cfg.CURRENT_POSITIONS[j] = 0 if j == 'hand' else 90
    return jsonify({'success': True})

if __name__ == '__main__':
    print('Starting app...')
    app.run(host='0.0.0.0', port=8080, threaded=True)
