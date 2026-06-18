from __future__ import annotations

import json
from pathlib import Path

from .models import Race


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "races.json"
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs"


def load_races(path: Path = DEFAULT_CONFIG) -> list[Race]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")
    races = [Race.from_dict(item) for item in raw]
    ids = [race.id for race in races]
    duplicates = sorted({race_id for race_id in ids if ids.count(race_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate race ids: {', '.join(duplicates)}")
    return races

