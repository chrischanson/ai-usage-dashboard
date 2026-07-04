#!/bin/bash
cd "$(dirname "$0")"
RUN_DIR="$(pwd)/run"
mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
source venv/bin/activate
cd backend
PYTHONPATH=. nohup python3 -m main > "$RUN_DIR/dashboard.log" 2>&1 &
PID=$!
echo $PID > "$RUN_DIR/dashboard.pid"
echo $PID
