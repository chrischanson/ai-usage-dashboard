#!/bin/bash
cd /home/dev/workspace/main/internal_projects/agy_quota_dashboard
source venv/bin/activate
cd backend
PYTHONPATH=. nohup python3 -m main > /tmp/dashboard.log 2>&1 &
echo $!
