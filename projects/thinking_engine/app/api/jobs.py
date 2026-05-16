"""Jobs API — CRUD endpoints for job definitions."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Job, Run
from app.core.scheduler import register_job, unregister_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Schemas ──────────────────────────────────────────────────

class JobCreate(BaseModel):
    name: str
    description: str | None = None
    schedule: str | None = None
    enabled: bool = True
    prompt_template: str
    context_config: list[dict[str, Any]] = Field(default_factory=list)
    budget_max_tokens: int = 2000
    budget_max_cost: float = 0.05
    fitness_config: dict[str, Any]


class JobUpdate(BaseModel):
    description: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    prompt_template: str | None = None
    context_config: list[dict[str, Any]] | None = None
    budget_max_tokens: int | None = None
    budget_max_cost: float | None = None
    fitness_config: dict[str, Any] | None = None


class JobResponse(BaseModel):
    id: str
    name: str
    description: str | None
    version: int
    schedule: str | None
    enabled: bool
    prompt_template: str
    context_config: list[dict[str, Any]]
    budget_max_tokens: int
    budget_max_cost: float
    fitness_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    run_count: int = 0
    avg_score: float | None = None

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────

@router.get("", response_model=list[JobResponse])
async def list_jobs(session: AsyncSession = Depends(get_session)):
    """List all jobs with run statistics."""
    result = await session.execute(select(Job).order_by(Job.created_at.desc()))
    jobs = result.scalars().all()

    responses = []
    for job in jobs:
        # Get run stats
        stats = await session.execute(
            select(
                func.count(Run.id),
                func.avg(Run.score),
            ).where(Run.job_id == job.id)
        )
        run_count, avg_score = stats.one()

        resp = JobResponse(
            id=str(job.id),
            name=job.name,
            description=job.description,
            version=job.version,
            schedule=job.schedule,
            enabled=job.enabled,
            prompt_template=job.prompt_template,
            context_config=job.context_config or [],
            budget_max_tokens=job.budget_max_tokens,
            budget_max_cost=float(job.budget_max_cost),
            fitness_config=job.fitness_config,
            created_at=job.created_at,
            updated_at=job.updated_at,
            run_count=run_count or 0,
            avg_score=round(float(avg_score), 4) if avg_score else None,
        )
        responses.append(resp)

    return responses


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    body: JobCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new job."""
    job = Job(
        name=body.name,
        description=body.description,
        schedule=body.schedule,
        enabled=body.enabled,
        prompt_template=body.prompt_template,
        context_config=body.context_config,
        budget_max_tokens=body.budget_max_tokens,
        budget_max_cost=Decimal(str(body.budget_max_cost)),
        fitness_config=body.fitness_config,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Register with scheduler if it has a schedule
    if job.schedule and job.enabled:
        register_job(job)

    return JobResponse(
        id=str(job.id),
        name=job.name,
        description=job.description,
        version=job.version,
        schedule=job.schedule,
        enabled=job.enabled,
        prompt_template=job.prompt_template,
        context_config=job.context_config or [],
        budget_max_tokens=job.budget_max_tokens,
        budget_max_cost=float(job.budget_max_cost),
        fitness_config=job.fitness_config,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get a single job by ID."""
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stats = await session.execute(
        select(func.count(Run.id), func.avg(Run.score)).where(Run.job_id == job.id)
    )
    run_count, avg_score = stats.one()

    return JobResponse(
        id=str(job.id),
        name=job.name,
        description=job.description,
        version=job.version,
        schedule=job.schedule,
        enabled=job.enabled,
        prompt_template=job.prompt_template,
        context_config=job.context_config or [],
        budget_max_tokens=job.budget_max_tokens,
        budget_max_cost=float(job.budget_max_cost),
        fitness_config=job.fitness_config,
        created_at=job.created_at,
        updated_at=job.updated_at,
        run_count=run_count or 0,
        avg_score=round(float(avg_score), 4) if avg_score else None,
    )


@router.put("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: uuid.UUID,
    body: JobUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a job definition."""
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    update_data = body.model_dump(exclude_unset=True)
    if "budget_max_cost" in update_data:
        update_data["budget_max_cost"] = Decimal(str(update_data["budget_max_cost"]))

    for field, value in update_data.items():
        setattr(job, field, value)

    job.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(job)

    # Re-register scheduler
    if job.schedule and job.enabled:
        register_job(job)
    else:
        unregister_job(str(job.id))

    return JobResponse(
        id=str(job.id),
        name=job.name,
        description=job.description,
        version=job.version,
        schedule=job.schedule,
        enabled=job.enabled,
        prompt_template=job.prompt_template,
        context_config=job.context_config or [],
        budget_max_tokens=job.budget_max_tokens,
        budget_max_cost=float(job.budget_max_cost),
        fitness_config=job.fitness_config,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Delete a job and all its runs."""
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    unregister_job(str(job.id))
    await session.delete(job)
    await session.commit()


@router.post("/{job_id}/run")
async def trigger_run(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Manually trigger a job run."""
    from app.core.executor import execute_job

    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    run = await execute_job(job, session)

    return {
        "run_id": str(run.id),
        "score": float(run.score) if run.score else None,
        "provider": run.provider,
        "model": run.model,
        "latency_ms": run.latency_ms,
        "error": run.error,
    }
