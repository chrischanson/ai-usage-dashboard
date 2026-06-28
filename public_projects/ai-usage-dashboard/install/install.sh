#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: sudo bash install/install.sh /path/to/project [user]"
    echo ""
    echo "Installs the AI Usage Dashboard auto-start on boot."
    echo "Detects systemd vs SysVinit and installs accordingly."
    echo ""
    echo "Arguments:"
    echo "  path    Absolute path to the project root (e.g. /home/user/ai-usage-dashboard)"
    echo "  user    User to run the dashboard as (default: current user)"
    echo ""
    echo "Example:"
    echo "  sudo bash install/install.sh /home/alice/ai-usage-dashboard alice"
    exit 1
fi

PROJECT_DIR="$(realpath "$1")"
PROJECT_USER="${2:-$USER}"

if [ ! -d "$PROJECT_DIR/backend" ]; then
    echo "Error: $PROJECT_DIR/backend does not exist. Is this the project root?"
    exit 1
fi

if ! id "$PROJECT_USER" &>/dev/null; then
    echo "Error: user $PROJECT_USER does not exist."
    exit 1
fi

if command -v systemctl &>/dev/null; then
    SERVICE_FILE="/etc/systemd/system/usage-dashboard.service"
    sed -e "s|PROJECT_DIR|$PROJECT_DIR|g" \
        -e "s|PROJECT_USER|$PROJECT_USER|g" \
        "$PROJECT_DIR/install/usage-dashboard.service" > "$SERVICE_FILE"
    chmod 644 "$SERVICE_FILE"
    systemctl daemon-reload
    systemctl enable usage-dashboard
    echo "Installed systemd service: usage-dashboard"
    echo ""
    echo "Start:  sudo systemctl start usage-dashboard"
    echo "Status: sudo systemctl status usage-dashboard"
    echo "Logs:   journalctl -u usage-dashboard -f"
else
    INIT_D_DIR="/etc/init.d"
    sed -e "s|PROJECT_DIR_PLACEHOLDER|$PROJECT_DIR|g" \
        -e "s|PROJECT_USER|$PROJECT_USER|g" \
        "$PROJECT_DIR/install/init.d/usage-dashboard" > "$INIT_D_DIR/usage-dashboard"
    chmod 755 "$INIT_D_DIR/usage-dashboard"
    update-rc.d usage-dashboard defaults 2>/dev/null || true
    echo "Installed init.d script: /etc/init.d/usage-dashboard"
    echo ""
    echo "Start:  sudo /etc/init.d/usage-dashboard start"
    echo "Enable: sudo update-rc.d usage-dashboard defaults"
fi
