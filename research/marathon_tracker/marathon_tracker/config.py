from __future__ import annotations

import json
from pathlib import Path

from .models import Race, RaceResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "races.json"
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs"
PREVIOUS_OUTPUT = PROJECT_ROOT / "docs" / "marathons.json"


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


def load_previous_output(path: Path = PREVIOUS_OUTPUT) -> dict[str, RaceResult] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    races_list = raw.get("races") if isinstance(raw, dict) else raw
    if not isinstance(races_list, list):
        return None
    return {item["id"]: RaceResult.from_dict(item) for item in races_list if isinstance(item, dict) and item.get("id")}


def save_races(races: list[Race], path: Path = DEFAULT_CONFIG) -> None:
    existing_ids = {r.id for r in load_races(path)} if path.exists() else set()
    new_entries = [r for r in races if r.id not in existing_ids]
    if not new_entries:
        return
    with path.open("r", encoding="utf-8") as handle:
        current = json.load(handle)
    if not isinstance(current, list):
        current = []
    for race in new_entries:
        current.append({
            "id": race.id,
            "name": race.name,
            "city": race.city,
            "country": race.country,
            "region": race.region,
            "official_url": race.official_url,
            "registration_url": race.registration_url,
            "source_url": race.source_url,
            "event_date": race.event_date,
            "registration_open_date": race.registration_open_date,
            "registration_deadline": race.registration_deadline,
            "lottery_deadline": race.lottery_deadline,
            "qualification_deadline": race.qualification_deadline,
            "confidence": race.confidence,
            "notes": race.notes,
        })
    with path.open("w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"saved {len(new_entries)} new race(s) to {path}")

