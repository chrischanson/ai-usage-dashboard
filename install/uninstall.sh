#!/bin/bash
set -euo pipefail

if command -v systemctl &>/dev/null; then
    SERVICE_FILE="/etc/systemd/system/usage-dashboard.service"
    if [ -f "$SERVICE_FILE" ]; then
        systemctl stop usage-dashboard 2>/dev/null || true
        systemctl disable usage-dashboard 2>/dev/null || true
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
        echo "Uninstalled systemd service: usage-dashboard"
    else
        echo "No systemd service found."
    fi
else
    INIT_D_SCRIPT="/etc/init.d/usage-dashboard"
    if [ -f "$INIT_D_SCRIPT" ]; then
        /etc/init.d/usage-dashboard stop 2>/dev/null || true
        update-rc.d -f usage-dashboard remove 2>/dev/null || true
        rm -f "$INIT_D_SCRIPT"
        echo "Uninstalled init.d script: /etc/init.d/usage-dashboard"
    else
        echo "No init.d script found."
    fi
fi
