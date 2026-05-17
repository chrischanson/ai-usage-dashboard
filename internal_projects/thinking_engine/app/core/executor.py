"""Executor — runs a single job end-to-end: context → LLM → evaluate → store."""

import logging
import time
import uuid
from decimal import Decimal

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.context import resolve_all_context
from app.core.evaluator import parse_output, score
from app.core.router import select_provider
from app.models import Run, DailySpend

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


async def execute_job(
    job,
    session: AsyncSession,
    variables: dict | None = None,
) -> Run:
    """
    Execute a single job run:
    1. Resolve context sources
    2. Render prompt template
    3. Select provider (cheapest available)
    4. Call LLM via litellm
    5. Parse output
    6. Score with evaluator
    7. Store run record
    """
    run_id = uuid.uuid4()
    start_time = time.monotonic()

    logger.info("Executing job '%s' (v%d) [run=%s]", job.name, job.version, run_id)

    # 1. Resolve context
    try:
        context = await resolve_all_context(
            job.context_config or [],
            session=session,
            variables=variables,
        )
    except Exception as e:
        logger.error("Context resolution failed for job '%s': %s", job.name, e)
        context = {}

    # 2. Render prompt template
    try:
        prompt = job.prompt_template.format(**context)
    except KeyError as e:
        logger.warning("Prompt template variable missing: %s, using raw template", e)
        prompt = job.prompt_template

    # 3. Select provider
    provider_config = await select_provider(job.budget_max_cost, session)

    # 4. Call LLM
    raw_output = None
    tokens_used = None
    cost_usd = Decimal("0")
    error = None

    try:
        # Set API key for litellm if needed
        if provider_config.api_key:
            # litellm reads from env or accepts api_key param
            pass

        # Configure Ollama base URL for litellm
        if provider_config.name == "ollama":
            litellm.api_base = settings.ollama_base_url

        response = await litellm.acompletion(
            model=provider_config.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=job.budget_max_tokens,
            api_key=provider_config.api_key if provider_config.api_key else None,
            api_base=settings.ollama_base_url if provider_config.name == "ollama" else None,
        )

        raw_output = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else None

        # Calculate cost
        if provider_config.cost_per_1k_tokens > 0 and tokens_used:
            cost_usd = Decimal(str(
                round(tokens_used / 1000 * provider_config.cost_per_1k_tokens, 6)
            ))

    except Exception as e:
        error = str(e)
        logger.error("LLM call failed for job '%s' on %s: %s", job.name, provider_config.name, e)

    latency_ms = int((time.monotonic() - start_time) * 1000)

    # 5. Parse output
    parsed_output = parse_output(raw_output) if raw_output else None

    # 6. Score
    if error:
        run_score = Decimal("0")
        score_details = {"error": error}
    else:
        run_score, score_details = await score(
            raw_output or "",
            parsed_output,
            job.fitness_config,
        )

    # 7. Store run
    run = Run(
        id=run_id,
        job_id=job.id,
        job_version=job.version,
        provider=provider_config.name,
        model=provider_config.model,
        prompt_sent=prompt[:10000],  # truncate very long prompts
        raw_output=raw_output,
        parsed_output=parsed_output,
        score=run_score,
        score_details=score_details,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        error=error,
    )
    session.add(run)

    # Update daily spend tracking
    try:
        from sqlalchemy import func, text
        result = await session.execute(
            select(DailySpend).where(
                DailySpend.date == func.current_date()
            )
        )
        daily = result.scalar_one_or_none()
        if daily:
            daily.total_usd += cost_usd
            daily.run_count += 1
        else:
            session.add(DailySpend(
                date=None,  # defaults to CURRENT_DATE in DB
                total_usd=cost_usd,
                run_count=1,
            ))
    except Exception as e:
        logger.warning("Failed to update daily spend: %s", e)

    await session.commit()

    logger.info(
        "Job '%s' completed: provider=%s score=%.4f cost=$%.6f latency=%dms",
        job.name, provider_config.name, run_score, cost_usd, latency_ms,
    )

    return run
