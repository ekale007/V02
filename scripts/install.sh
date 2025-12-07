#!/usr/bin/env bash
set -euo pipefail

# install.sh — simple installer for Robot Arm app on Raspberry Pi
# Usage: sudo ./scripts/install.sh [--user USER] [--venv-dir PATH] [--no-systemd] [--yes]
# Defaults assume project is checked out at /home/pi/robot-arm and current user is 'pi'.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un 2>/dev/null || echo pi)"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="robot-arm.service"
INSTALL_SYSTEMD=true
AUTO_YES=false

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2;;
    --venv-dir) VENV_DIR="$2"; shift 2;;
    --no-systemd) INSTALL_SYSTEMD=false; shift;;
    --yes) AUTO_YES=true; shift;;
    -h|--help) echo "Usage: sudo ./scripts/install.sh [--user USER] [--venv-dir PATH] [--no-systemd] [--yes]"; exit 0;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

echo "Project dir: $PROJECT_DIR"
echo "User: $USER_NAME"
echo "Virtualenv: $VENV_DIR"

confirm(){
  if [ "$AUTO_YES" = true ]; then
    return 0
  fi
  read -r -p "$1 [y/N]: " ans
  case "$ans" in
    [Yy]*) return 0;;
    *) return 1;;
  esac
}

# 1) Ensure Python 3 and venv available
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 not found. Install Python 3 first." >&2
  exit 2
fi

# create venv if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv in $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
else
  echo "Virtualenv exists at $VENV_DIR"
fi

# 2) Activate venv and install requirements
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

if [ -f "$PROJECT_DIR/requirements.txt" ]; then
  echo "Installing Python requirements..."
  pip install --upgrade pip
  pip install -r "$PROJECT_DIR/requirements.txt"
else
  echo "No requirements.txt found in project dir — skipping pip install"
fi

# 3) Create default calib.json and sim.json if they don't exist
CALIB_FILE="$PROJECT_DIR/calib.json"
SIM_FILE="$PROJECT_DIR/sim.json"

if [ ! -f "$CALIB_FILE" ]; then
  echo "Writing default calib.json"
  cat > "$CALIB_FILE" <<JSON
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
  }
}
JSON
else
  echo "calib.json already exists — skipping"
fi

if [ ! -f "$SIM_FILE" ]; then
  echo "Writing default sim.json"
  cat > "$SIM_FILE" <<JSON
{
  "lengths": {"shoulder": 90, "elbow": 70, "wrist": 50, "hand": 20},
  "origin": {"x": 210, "y": 260},
  "scale": 1.0
}
JSON
else
  echo "sim.json already exists — skipping"
fi

# 4) Ensure project ownership for runtime user
if [ "$(id -un)" != "$USER_NAME" ]; then
  echo "Setting ownership of project files to $USER_NAME (requires sudo)"
  if command -v sudo >/dev/null 2>&1; then
    sudo chown -R "$USER_NAME":"$USER_NAME" "$PROJECT_DIR"
  else
    echo "Warning: sudo not available — skip chown" >&2
  fi
fi

# 5) Install systemd service (optional)
if [ "$INSTALL_SYSTEMD" = true ]; then
  SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
  echo "Preparing systemd service at $SERVICE_PATH"
  if confirm "Install and enable systemd service ($SERVICE_NAME)?"; then
    SERVICE_EXEC="${VENV_DIR}/bin/python3 $PROJECT_DIR/app.py"
    SERVICE_UNIT="[Unit]\nDescription=Robot Arm Control Web UI\nAfter=network.target\n\n[Service]\nUser=$USER_NAME\nWorkingDirectory=$PROJECT_DIR\nExecStart=$SERVICE_EXEC\nRestart=always\nRestartSec=5\nEnvironment=PYTHONUNBUFFERED=1\n\n[Install]\nWantedBy=multi-user.target\n"
    echo "Writing service unit (requires sudo)"
    echo -e "$SERVICE_UNIT" | sudo tee "$SERVICE_PATH" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME"
    echo "systemd service installed and started"
  else
    echo "Skipping systemd installation"
  fi
fi

# 6) Print next steps
cat <<EOF

Installation finished.
- Virtualenv: $VENV_DIR
- To run manually: . "$VENV_DIR/bin/activate" && python3 $PROJECT_DIR/app.py
- If you installed systemd service: sudo systemctl status $SERVICE_NAME

EOF
