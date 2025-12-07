"""Simple kinematics helper module for the robot arm.
This module contains utilities for home positions, angle clamping and
predefined program sequences (wave, pick & place) as data structures.

The real inverse/forward kinematics depend on your arm geometry. For a
basic servo-driven demo we provide sequence builders that the web app can
use without embedding hardware logic.
"""

from typing import Dict, List, Any

# Logical joint names used across the project
JOINTS = ["base", "shoulder", "elbow", "wrist", "hand"]

# Home positions (degrees). Hand (gripper) default = 0 (open)
_HOME = {
    "base": 90,
    "shoulder": 90,
    "elbow": 90,
    "wrist": 90,
    "hand": 0,
}

# Joint limits (min, max) in degrees - tweak to your servos
_LIMITS = {
    "base": (0, 180),
    "shoulder": (15, 165),
    "elbow": (0, 180),
    "wrist": (0, 180),
    "hand": (0, 90),
}


def clamp_angle(joint: str, angle: int) -> int:
    """Clamp an angle to the configured joint limits."""
    if joint not in _LIMITS:
        return max(0, min(180, int(angle)))
    lo, hi = _LIMITS[joint]
    a = int(angle)
    if a < lo:
        return lo
    if a > hi:
        return hi
    return a


def get_home_positions() -> Dict[str, int]:
    """Return a copy of home positions dict."""
    return dict(_HOME)


def wave_sequence(cycles: int = 3) -> List[Dict[str, Any]]:
    """Return a list of steps for a waving program.
Each step is a dict: {"positions": {joint:angle,...}, "delay": seconds}
"""
    steps: List[Dict[str, Any]] = []

    # move to home first
    steps.append({"positions": get_home_positions(), "delay": 1.0})

    for _ in range(cycles):
        steps.append({"positions": {"shoulder": 60, "elbow": 120}, "delay": 0.5})
        steps.append({"positions": {"shoulder": 120, "elbow": 60}, "delay": 0.5})

    steps.append({"positions": get_home_positions(), "delay": 1.0})
    return steps


def pickplace_sequence() -> List[Dict[str, Any]]:
    """Return a pick & place sequence as a list of timed steps."""
    steps: List[Dict[str, Any]] = []

    # 1. Move to pick position
    steps.append({"positions": {"base": 60, "shoulder": 120, "elbow": 60, "wrist": 120, "hand": 0}, "delay": 1.0})
    # 2. Close gripper
    steps.append({"positions": {"hand": 90}, "delay": 1.0})
    # 3. Lift
    steps.append({"positions": {"shoulder": 90, "elbow": 90}, "delay": 1.0})
    # 4. Rotate
    steps.append({"positions": {"base": 120}, "delay": 1.0})
    # 5. Place
    steps.append({"positions": {"shoulder": 120, "elbow": 60}, "delay": 1.0})
    # 6. Open gripper
    steps.append({"positions": {"hand": 0}, "delay": 1.0})
    # 7. Home
    steps.append({"positions": get_home_positions(), "delay": 1.0})

    return steps


# Small helper to apply clamps to a dict of positions
def clamp_positions(positions: Dict[str, int]) -> Dict[str, int]:
    return {j: clamp_angle(j, positions.get(j, _HOME[j])) for j in JOINTS}


# Exported names
__all__ = [
    "JOINTS",
    "get_home_positions",
    "clamp_angle",
    "clamp_positions",
    "wave_sequence",
    "pickplace_sequence",
]
