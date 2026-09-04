"""Entry point for the AI Usage Dashboard."""
import logging
import os
import uvicorn
from api import create_app
from config import load_config, setup_logging
from db import connect, init_schema
from poller import Poller

logger = logging.getLogger(__name__)


def main():
    cfg = load_config()
    setup_logging(cfg.log_level)

    # Load YAML-based providers (replaces hardcoded sources if providers/ exists)
    providers_dir = os.path.join(os.path.dirname(__file__), 'providers')
    from source_registry import load_from_providers
    load_from_providers(providers_dir, cfg)

    conn = connect(cfg.db_path)
    init_schema(conn)
    from integrity import check_integrity
    report = check_integrity(conn, cfg.poll_interval)
    for warning in report['warnings']:
        logger.warning("startup integrity: %s", warning)
    conn.close()

    # The app owns the poller: its lifespan starts it and, more importantly,
    # stops it on shutdown. Signals are left entirely to uvicorn, which
    # installs its own SIGTERM/SIGINT handlers when it runs -- handlers
    # registered here beforehand were simply overwritten, so the poller never
    # got a clean stop. The app object is passed directly rather than as an
    # "api:create_app" factory string because the factory form cannot be
    # handed a Config or a Poller.
    poller = Poller(cfg)
    app = create_app(cfg, poller=poller)

    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        # Leave logging alone: uvicorn's default log_config replaces the root
        # handler, which would emit its own lines in plain text next to the
        # application's JSON. With it disabled, uvicorn's loggers propagate to
        # the handler setup_logging installed, so the whole stream is JSON.
        log_config=None,
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
