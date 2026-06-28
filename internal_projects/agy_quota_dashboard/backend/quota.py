import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from config import Config


def collect(source: str, cfg: Config) -> dict | None:
    if source == 'agy':
        return _collect_agy(cfg)
    elif source == 'opencode':
        return _collect_opencode(cfg)
    elif source == 'codex':
        return _collect_codex(cfg)
    raise ValueError(f"unknown quota source: {source}")


def _collect_agy(cfg: Config) -> dict | None:
    try:
        from quota_parser import fetch_agy_quota
        return fetch_agy_quota()
    except Exception:
        return None


def _collect_opencode(cfg: Config) -> dict | None:
    try:
        from opencode_quota import fetch_opencode_cost
        return fetch_opencode_cost()
    except Exception:
        return None


def _collect_codex(cfg: Config) -> dict | None:
    try:
        from codex_quota import fetch_codex_quota
        return fetch_codex_quota()
    except Exception:
        return None
