#!/bin/bash
cd /home/dev/workspace/main/internal_projects/agy_quota_dashboard
source venv/bin/activate
PYTHONPATH=. nohup python3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 > /tmp/dashboard.log 2>&1 &
echo $!
