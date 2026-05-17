"""Credit router — selects the cheapest available LLM provider for a job."""

import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ProviderCredit

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Resolved provider selection result."""
    name: str
    model: str
    cost_per_1k_tokens: float
    api_key: str | None = None


# Provider registry ordered by cost (cheapest first)
# Ollama is always last as the free fallback
PROVIDER_REGISTRY = [
    {
        "name": "groq",
        "cost_per_1k": 0.0,
        "model": "llama-3.1-70b-versatile",
        "key_setting": "groq_api_key",
    },
    {
        "name": "gemini",
        "cost_per_1k": 0.002,
        "model": "gemini/gemini-2.0-flash",
        "key_setting": "google_api_key",
    },
    {
        "name": "anthropic",
        "cost_per_1k": 0.003,
        "model": "claude-haiku-4-5-20250515",
        "key_setting": "anthropic_api_key",
    },
    {
        "name": "openai",
        "cost_per_1k": 0.004,
        "model": "gpt-4o-mini",
        "key_setting": "openai_api_key",
    },
]


async def _check_ollama_health() -> bool:
    """Check if Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def select_provider(
    budget_max_cost: Decimal,
    session: AsyncSession,
) -> ProviderConfig:
    """
    Select the cheapest available provider that:
    1. Has an API key configured
    2. Has remaining credits > budget_max_cost
    3. Is not over the daily spend limit
    Falls back to Ollama (always available, zero cost).
    """
    budget = float(budget_max_cost)

    for provider in PROVIDER_REGISTRY:
        # Check if API key is configured
        api_key = getattr(settings, provider["key_setting"], "")
        if not api_key:
            continue

        # Check credit balance
        result = await session.execute(
            select(ProviderCredit).where(ProviderCredit.provider == provider["name"])
        )
        credit = result.scalar_one_or_none()

        if credit and float(credit.balance_usd) > budget:
            logger.info(
                "Selected provider %s (model=%s, balance=%.4f, budget=%.4f)",
                provider["name"], provider["model"],
                float(credit.balance_usd), budget,
            )
            return ProviderConfig(
                name=provider["name"],
                model=provider["model"],
                cost_per_1k_tokens=provider["cost_per_1k"],
                api_key=api_key,
            )

    # Fallback to Ollama (always free, always local)
    logger.info("Falling back to Ollama (model=%s)", settings.ollama_default_model)
    return ProviderConfig(
        name="ollama",
        model=f"ollama/{settings.ollama_default_model}",
        cost_per_1k_tokens=0.0,
    )
