"""Scheduler — APScheduler setup with PostgreSQL persistence."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models import Job

logger = logging.getLogger(__name__)

# Use a synchronous URL for APScheduler's SQLAlchemy job store
# (APScheduler 3.x doesn't support async drivers for job storage)
_sync_db_url = settings.database_url.replace(
    "postgresql+asyncpg", "postgresql+psycopg2"
).replace(
    "postgresql+asyncpg", "postgresql"
)

# If the URL still uses asyncpg, fall back to basic postgresql
if "asyncpg" in _sync_db_url:
    _sync_db_url = _sync_db_url.replace("asyncpg", "psycopg2")


scheduler = AsyncIOScheduler(
    jobstores={
        "default": SQLAlchemyJobStore(url=_sync_db_url, tablename="apscheduler_jobs"),
    },
    job_defaults={
        "coalesce": True,         # Combine missed runs into one
        "max_instances": 1,       # One instance per job at a time
        "misfire_grace_time": 300,  # 5 min grace for misfires
    },
)


async def _run_scheduled_job(job_id: str):
    """Callback invoked by APScheduler — loads the job and executes it."""
    from app.core.executor import execute_job

    async with async_session() as session:
        result = await session.execute(
            select(Job).where(Job.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            logger.error("Scheduled job %s not found in DB", job_id)
            return

        if not job.enabled:
            logger.info("Skipping disabled job '%s'", job.name)
            return

        try:
            run = await execute_job(job, session)
            logger.info(
                "Scheduled run complete: job='%s' score=%.4f",
                job.name, run.score or 0,
            )
        except Exception as e:
            logger.error("Scheduled job '%s' failed: %s", job.name, e, exc_info=True)


def register_job(job: Job):
    """Register a single job with the scheduler."""
    if not job.schedule:
        logger.info("Job '%s' has no schedule, skipping registration", job.name)
        return

    job_id = str(job.id)

    try:
        trigger = CronTrigger.from_crontab(job.schedule)
    except ValueError as e:
        logger.error("Invalid cron expression for job '%s': %s", job.name, e)
        return

    # Remove existing schedule if present (idempotent re-registration)
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    scheduler.add_job(
        _run_scheduled_job,
        trigger=trigger,
        id=job_id,
        args=[job_id],
        name=f"job:{job.name}",
        replace_existing=True,
    )
    logger.info("Registered job '%s' with schedule '%s'", job.name, job.schedule)


def unregister_job(job_id: str):
    """Remove a job from the scheduler."""
    try:
        scheduler.remove_job(str(job_id))
    except Exception:
        pass


async def load_all_jobs():
    """Load all enabled jobs from DB and register them with the scheduler."""
    async with async_session() as session:
        result = await session.execute(
            select(Job).where(Job.enabled == True)
        )
        jobs = result.scalars().all()

        for job in jobs:
            register_job(job)

        logger.info("Loaded %d jobs from database", len(jobs))
