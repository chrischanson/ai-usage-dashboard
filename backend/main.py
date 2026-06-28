"""Entry point for the AI Usage Dashboard."""
import signal
import sys
import uvicorn
from config import load_config
from db import connect, init_schema
from poller import Poller


def main():
    cfg = load_config()

    conn = connect(cfg.db_path)
    init_schema(conn)
    conn.close()

    poller = Poller(cfg)
    poller.start()

    def shutdown(sig, frame):
        poller.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    uvicorn.run(
        "api:create_app",
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        factory=True,
    )


if __name__ == "__main__":
    main()
