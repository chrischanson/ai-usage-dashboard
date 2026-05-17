"""Thinking Engine — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import jobs, runs, system
from app.core.scheduler import scheduler, load_all_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop scheduler."""
    logger.info("Starting Thinking Engine...")

    # Start the scheduler
    scheduler.start()
    logger.info("APScheduler started")

    # Load all enabled jobs from DB
    try:
        await load_all_jobs()
    except Exception as e:
        logger.error("Failed to load jobs from DB: %s", e)

    yield

    # Shutdown
    scheduler.shutdown(wait=True)
    logger.info("Thinking Engine stopped")


app = FastAPI(
    title="Thinking Engine",
    description="Self-hosted, self-improving agentic pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

# Register API routers
app.include_router(system.router)
app.include_router(jobs.router)
app.include_router(runs.router)
