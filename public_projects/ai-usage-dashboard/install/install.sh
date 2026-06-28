#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: sudo bash install/install.sh /path/to/project [user]"
    echo ""
    echo "Installs the AGY Quota Dashboard as a systemd service."
    echo ""
    echo "Arguments:"
    echo "  path    Absolute path to the project root (e.g. /home/user/agy-quota-dashboard)"
    echo "  user    System user to run the service as (default: current \$USER)"
    echo ""
    echo "Example:"
    echo "  sudo bash install/install.sh /home/alice/agy-quota-dashboard alice"
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

SERVICE_FILE="/etc/systemd/system/agy-dashboard.service"

sed -e "s|PROJECT_DIR|$PROJECT_DIR|g" \
    -e "s|PROJECT_USER|$PROJECT_USER|g" \
    "$PROJECT_DIR/install/agy-dashboard.service" > "$SERVICE_FILE"

chmod 644 "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable agy-dashboard

echo "Installed agy-dashboard.service"
echo ""
echo "Start it now:  sudo systemctl start agy-dashboard"
echo "Check status:  sudo systemctl status agy-dashboard"
echo "View logs:     journalctl -u agy-dashboard -f"
echo "Stop:          sudo systemctl stop agy-dashboard"
echo "Restart:       sudo systemctl restart agy-dashboard"
