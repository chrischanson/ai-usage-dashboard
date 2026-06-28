#!/bin/bash
set -euo pipefail

SERVICE_FILE="/etc/systemd/system/agy-dashboard.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "Service not installed (no $SERVICE_FILE found)."
    exit 0
fi

systemctl stop agy-dashboard 2>/dev/null || true
systemctl disable agy-dashboard 2>/dev/null || true
rm -f "$SERVICE_FILE"
systemctl daemon-reload

echo "Uninstalled agy-dashboard.service"
