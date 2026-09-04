#!/bin/bash
set -e

# Resolve script directory relative to the script location
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/backend"

# Create a virtual environment if it doesn't exist, and install deps only then
NEW_VENV=0
if [ ! -d "../venv" ]; then
    python3 -m venv ../venv
    NEW_VENV=1
fi

# Activate virtual environment
source ../venv/bin/activate

if [[ "$NEW_VENV" == "1" || "$1" == "--update-deps" ]]; then
    # Install dependencies. The externally-managed-environment warning is noise
    # inside a venv, so it is filtered from the output -- but a real pip failure
    # must abort rather than leave a half-installed environment behind.
    #
    # `if ! VAR=$(...)` is deliberate: a bare `VAR=$(...)` assignment is subject
    # to `set -e`, so the script would exit on failure before reaching any error
    # handling, and piping pip straight into grep would hide its exit status.
    if ! PIP_OUTPUT=$(pip install -q -r ../requirements.txt 2>&1); then
        [ -n "$PIP_OUTPUT" ] && printf '%s\n' "$PIP_OUTPUT" | grep -v "externally-managed"
        echo "run.sh: pip install failed; the virtualenv at ../venv may be incomplete." >&2
        echo "run.sh: fix the error above, then re-run with --update-deps." >&2
        exit 1
    fi
    [ -n "$PIP_OUTPUT" ] && printf '%s\n' "$PIP_OUTPUT" | grep -v "externally-managed"
fi

RUN_DIR="$SCRIPT_DIR/run"
mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
PIDFILE="$RUN_DIR/dashboard.pid"
LOGFILE="$RUN_DIR/dashboard.log"

# Kill only our previously-started instance, if its recorded PID is still alive
# (never a blanket "pkill -f uvicorn", which would kill unrelated processes).
if [ -f "$PIDFILE" ]; then
    OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping previous instance (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PIDFILE"
fi

HOST="${USAGE_HOST:-127.0.0.1}"
PORT="${USAGE_PORT:-8000}"

# Run via main entry point (handles poller + graceful shutdown)
if [[ "$1" == "--background" || "$1" == "-b" ]]; then
    echo "Starting Uvicorn server in background (detached)..."
    nohup ../venv/bin/python -m main > "$LOGFILE" 2>&1 &
    PID=$!
    echo $PID > "$PIDFILE"
    disown
    echo "Server started in background. Logs are written to $LOGFILE"
else
    echo "Starting Uvicorn server in foreground..."
    ../venv/bin/python -m main
fi
