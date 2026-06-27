#!/bin/bash
set -e

# Resolve script directory relative to the script location
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Kill any existing process on port 8000
echo "Cleaning up existing processes on port 8000..."
pkill -f "uvicorn backend.app:app" 2>/dev/null || true
sleep 1

HOST="0.0.0.0"
PORT="8000"

# Run the FastAPI server
if [[ "$1" == "--background" || "$1" == "-b" ]]; then
    echo "Starting Uvicorn server in background (detached)..."
    nohup python3 -m uvicorn backend.app:app --host "$HOST" --port "$PORT" > dashboard.log 2>&1 &
    disown
    echo "Server started in background. Logs are written to dashboard.log"
else
    echo "Starting Uvicorn server in foreground..."
    python3 -m uvicorn backend.app:app --host "$HOST" --port "$PORT"
fi

