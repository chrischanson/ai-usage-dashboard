#!/usr/bin/env bash
# run_update.sh - Wrapper script to run marathon tracker updates on your devserver.
#
# To automate this via cron, run 'crontab -e' and add a line like:
# 17 8 * * * LLM_API_KEY="your_api_key_here" /home/dev/workspace/main/research/marathon_tracker/run_update.sh >> /home/dev/workspace/main/research/marathon_tracker/update.log 2>&1
#
# To target a specific marathon and skip the rest, run:
# ./run_update.sh --race-id london-marathon

set -e

# Resolve the directory where this script resides and the repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"


# Change directory to repo root so python can locate the module correctly
cd "$REPO_ROOT"

# Run the update script, forwarding any arguments (e.g. --no-network or --limit)
python3 -m research.marathon_tracker.marathon_tracker.update "$@"
