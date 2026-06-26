#!/bin/bash
set -e

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server using uvicorn
python3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
