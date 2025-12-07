"""UI and mapping configuration kept separate from application logic.
This file is intentionally small and editable by non-Python users.
"""

SERVO_MAP = {
    "base": 0,
    "shoulder": 1,
    "elbow": 2,
    "wrist": 3,
    "hand": 4,
}

CURRENT_POSITIONS = {
    "base": 90,
    "shoulder": 90,
    "elbow": 90,
    "wrist": 90,
    "hand": 0,
}

UI_META = {
    "app_name": "Robot Arm Control",
    "version": "1.0",
}
