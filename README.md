# Robot Arm - Refactor

Dieses Repository enthält eine aufgeteilte Version deiner bisherigen App:

- kinematics.py  — Kinematik- und Sequenz-Builder (home, wave, pickplace)
- hw_manager.py  — ServoManager (Thread, Queue, Not-Aus)
- ui_config.py   — Mapping & UI-Defaults
- app.py         — Flask App und API
- templates/     — HTML-Template

Installation & Start (auf Raspberry Pi):

1) Systemabhängigkeiten:
   sudo apt update && sudo apt install -y python3-venv i2c-tools
2) Virtualenv (empfohlen):
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
3) Starten:
   python3 app.py

Sicherheit: Das UI hat keine Authentifizierung. Nur im privaten LAN oder hinter VPN verwenden!
