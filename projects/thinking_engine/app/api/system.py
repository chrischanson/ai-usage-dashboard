"""System API — health, providers, and aggregate stats."""

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Run, ProviderCredit, Feedback
from app.core.scheduler import scheduler

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """Liveness check."""
    return {"status": "ok", "service": "thinking-engine"}


@router.get("/api/providers")
async def list_providers(session: AsyncSession = Depends(get_session)):
    """List all providers with credit balances."""
    result = await session.execute(
        select(ProviderCredit).order_by(ProviderCredit.provider)
    )
    credits = result.scalars().all()

    return [
        {
            "provider": c.provider,
            "balance_usd": float(c.balance_usd),
            "daily_limit": float(c.daily_limit) if c.daily_limit else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in credits
    ]


@router.get("/api/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Aggregate statistics across all jobs."""
    # Total runs
    total_runs = await session.execute(select(func.count(Run.id)))
    total_run_count = total_runs.scalar() or 0

    # Average score
    avg_score_result = await session.execute(
        select(func.avg(Run.score)).where(Run.score.isnot(None))
    )
    avg_score = avg_score_result.scalar()

    # Total spend
    total_spend_result = await session.execute(
        select(func.sum(Run.cost_usd)).where(Run.cost_usd.isnot(None))
    )
    total_spend = total_spend_result.scalar()

    # Alert precision (from feedback)
    total_feedback = await session.execute(select(func.count(Feedback.id)))
    useful_feedback = await session.execute(
        select(func.count(Feedback.id)).where(Feedback.useful == True)
    )
    total_fb = total_feedback.scalar() or 0
    useful_fb = useful_feedback.scalar() or 0
    precision = round(useful_fb / total_fb, 4) if total_fb > 0 else None

    # Scheduled jobs
    scheduled_jobs = scheduler.get_jobs()

    return {
        "total_runs": total_run_count,
        "avg_score": round(float(avg_score), 4) if avg_score else None,
        "total_spend_usd": round(float(total_spend), 6) if total_spend else 0,
        "alert_precision": precision,
        "feedback_count": total_fb,
        "scheduled_jobs": len(scheduled_jobs),
    }
