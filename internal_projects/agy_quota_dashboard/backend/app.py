import asyncio
import threading
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import uvicorn
from .db import init_db, insert_usage, get_latest_usage, get_history_series
from .parser import fetch_and_parse

app = FastAPI()

# Initialize DB on startup
@app.on_event("startup")
def startup_event():
    init_db()
    # Start background polling thread
    def poll_usage():
        import time
        while True:
            try:
                overview, cost_tokens, models = fetch_and_parse()
                if overview or cost_tokens:
                    insert_usage(overview, cost_tokens, models)
            except Exception as e:
                print(f"Error polling usage: {e}")
            time.sleep(600)  # Sleep for 10 minutes

    t = threading.Thread(target=poll_usage, daemon=True)
    t.start()

@app.get("/api/usage/latest")
def api_latest_usage():
    data = get_latest_usage()
    return data if data else {}

@app.get("/api/usage/history")
def api_usage_history():
    return get_history_series()

# Mount frontend
frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def read_root():
    return RedirectResponse(url='/static/index.html')

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)
