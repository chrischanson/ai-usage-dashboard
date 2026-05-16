"""Context resolvers — fetch and inject data into prompt templates."""

import logging
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Run

logger = logging.getLogger(__name__)


async def resolve_prior_results(
    config: dict,
    session: AsyncSession,
) -> str:
    """
    Fetch the last N results from a specific job for context injection.

    Config keys:
        job_id: name of the job to pull results from
        last_n: number of recent results to include (default 5)
    """
    job_name = config.get("job_id", "")
    last_n = config.get("last_n", 5)

    result = await session.execute(
        select(Run)
        .join(Run.job)
        .where(Run.job.has(name=job_name))
        .where(Run.error.is_(None))
        .order_by(desc(Run.created_at))
        .limit(last_n)
    )
    runs = result.scalars().all()

    if not runs:
        return "(no prior results available)"

    lines = []
    for run in runs:
        output_summary = str(run.parsed_output or run.raw_output or "")[:500]
        lines.append(f"- [{run.created_at.isoformat()}] score={run.score}: {output_summary}")

    return "\n".join(lines)


async def resolve_static_text(config: dict, **kwargs) -> str:
    """Inject a static text block as context."""
    return config.get("text", "")


# Registry of context resolvers
RESOLVER_REGISTRY = {
    "prior_results": resolve_prior_results,
    "static": resolve_static_text,
    # Future: "web_search", "rss", "file"
}


async def resolve_all_context(
    context_configs: list[dict],
    session: AsyncSession,
    variables: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Resolve all context sources for a job and return a dict of
    variable_name -> resolved_text for template rendering.
    """
    variables = variables or {}
    resolved = {}

    for config in context_configs:
        ctx_type = config.get("type", "")
        var_name = config.get("as", ctx_type)  # default var name = type name

        resolver = RESOLVER_REGISTRY.get(ctx_type)
        if not resolver:
            logger.warning("Unknown context type: %s, skipping", ctx_type)
            resolved[var_name] = f"(unknown context type: {ctx_type})"
            continue

        try:
            result = await resolver(config, session=session)
            resolved[var_name] = result
        except Exception as e:
            logger.error("Failed to resolve context %s: %s", ctx_type, e)
            resolved[var_name] = f"(error resolving {ctx_type}: {e})"

    # Merge with any provided variables
    resolved.update(variables)
    return resolved
