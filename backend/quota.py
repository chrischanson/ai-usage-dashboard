from config import Config
from source_registry import get_source


def collect(source: str, cfg: Config) -> dict | None:
    entry = get_source(source)
    if not entry or not entry.quota_collector:
        raise ValueError(f"unknown quota source: {source}")
    try:
        return entry.quota_collector()
    except Exception:
        return None
