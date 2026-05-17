"""Runs API — query run history and details."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Run, Feedback

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunResponse(BaseModel):
    id: str
    job_id: str
    job_version: int
    provider: str
    model: str
    prompt_sent: str | None
    raw_output: str | None
    parsed_output: dict[str, Any] | None
    score: float | None
    score_details: dict[str, Any] | None
    tokens_used: int | None
    cost_usd: float | None
    latency_ms: int | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackCreate(BaseModel):
    useful: bool
    note: str | None = None


@router.get("", response_model=list[RunResponse])
async def list_runs(
    job_id: uuid.UUID | None = Query(None),
    min_score: float | None = Query(None),
    max_score: float | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    """List runs with optional filters."""
    query = select(Run).order_by(desc(Run.created_at))

    if job_id:
        query = query.where(Run.job_id == job_id)
    if min_score is not None:
        query = query.where(Run.score >= min_score)
    if max_score is not None:
        query = query.where(Run.score <= max_score)

    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    runs = result.scalars().all()

    return [
        RunResponse(
            id=str(r.id),
            job_id=str(r.job_id),
            job_version=r.job_version,
            provider=r.provider,
            model=r.model,
            prompt_sent=r.prompt_sent,
            raw_output=r.raw_output,
            parsed_output=r.parsed_output,
            score=float(r.score) if r.score is not None else None,
            score_details=r.score_details,
            tokens_used=r.tokens_used,
            cost_usd=float(r.cost_usd) if r.cost_usd is not None else None,
            latency_ms=r.latency_ms,
            error=r.error,
            created_at=r.created_at,
        )
        for r in runs
    ]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get a single run by ID."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunResponse(
        id=str(run.id),
        job_id=str(run.job_id),
        job_version=run.job_version,
        provider=run.provider,
        model=run.model,
        prompt_sent=run.prompt_sent,
        raw_output=run.raw_output,
        parsed_output=run.parsed_output,
        score=float(run.score) if run.score is not None else None,
        score_details=run.score_details,
        tokens_used=run.tokens_used,
        cost_usd=float(run.cost_usd) if run.cost_usd is not None else None,
        latency_ms=run.latency_ms,
        error=run.error,
        created_at=run.created_at,
    )


@router.post("/{run_id}/feedback", status_code=201)
async def submit_feedback(
    run_id: uuid.UUID,
    body: FeedbackCreate,
    session: AsyncSession = Depends(get_session),
):
    """Submit thumbs up/down feedback for a run."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    fb = Feedback(run_id=run_id, useful=body.useful, note=body.note)
    session.add(fb)
    await session.commit()

    return {"status": "ok", "feedback_id": str(fb.id)}
