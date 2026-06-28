#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
cd backend
PYTHONPATH=. nohup python3 -m main > /tmp/dashboard.log 2>&1 &
echo $!
