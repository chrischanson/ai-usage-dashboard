"""Entry point for the AI Usage Dashboard."""
import logging
import signal
import sys
import uvicorn
from config import load_config
from db import connect, init_schema
from poller import Poller


def main():
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    conn = connect(cfg.db_path)
    init_schema(conn)
    from integrity import check_integrity
    report = check_integrity(conn, cfg.poll_interval)
    for warning in report['warnings']:
        print(f"[startup] integrity: {warning}")
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
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
