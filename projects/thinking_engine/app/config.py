"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is loaded from environment variables or .env file."""

    # Database
    database_url: str = "postgresql+asyncpg://engine:engine-dev@db:5432/thinking_engine"

    # Ollama (local LLM fallback)
    ollama_base_url: str = "http://ollama:11434"
    ollama_default_model: str = "qwen3:8b"

    # LLM Provider API Keys
    groq_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # Spend controls
    daily_spend_limit_usd: float = 2.0

    # Evolution settings
    evolution_min_runs: int = 20
    evolution_holdout_pct: float = 0.2

    # Notifications
    alert_score_threshold: float = 0.85
    ntfy_topic: str = ""
    slack_webhook_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
