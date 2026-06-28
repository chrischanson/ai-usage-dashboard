#!/bin/bash
set -e

# Resolve script directory relative to the script location
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/backend"

# Create a virtual environment if it doesn't exist
if [ ! -d "../venv" ]; then
    python3 -m venv ../venv
fi

# Activate virtual environment
source ../venv/bin/activate

# Install dependencies (suppress externally-managed-environment warning inside venv)
pip install -q -r ../requirements.txt 2>&1 | grep -v "externally-managed" || true

# Kill any existing process on port 8000
echo "Cleaning up existing processes on port 8000..."
pkill -f "uvicorn" 2>/dev/null || true
sleep 1

HOST="${USAGE_HOST:-127.0.0.1}"
PORT="${USAGE_PORT:-8000}"

# Run via main entry point (handles poller + graceful shutdown)
if [[ "$1" == "--background" || "$1" == "-b" ]]; then
    echo "Starting Uvicorn server in background (detached)..."
    nohup python3 -m main > ../dashboard.log 2>&1 &
    disown
    echo "Server started in background. Logs are written to dashboard.log"
else
    echo "Starting Uvicorn server in foreground..."
    python3 -m main
fi
