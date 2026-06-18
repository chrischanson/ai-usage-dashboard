from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import RaceResult


def write_outputs(results: list[RaceResult], docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(results),
        "races": [result.to_dict() for result in sorted(results, key=lambda item: (item.region, item.name))],
    }
    (docs_dir / "marathons.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (docs_dir / "marathons.md").write_text(render_markdown(payload), encoding="utf-8")


def render_markdown(payload: dict[str, object]) -> str:
    races = payload["races"]
    assert isinstance(races, list)
    generated_at = str(payload["generated_at"])
    count = str(payload["count"])

    lines = [
        "# Marathon Tracker",
        "",
        f"{count} races tracked. Generated {generated_at} UTC from official race pages where available.",
        "",
        "## Races",
        "",
        "| Race | Location | Region | Event Date | Registration Opens | Registration Deadline | Lottery Deadline | Qualification Deadline | Status | Confidence | Source |",
        "|------|----------|--------|------------|-------------------|-----------------------|------------------|------------------------|--------|------------|--------|",
    ]

    for race in races:
        if not isinstance(race, dict):
            continue
        name = _esc(race.get("name", ""))
        city = _esc(race.get("city", ""))
        country = _esc(race.get("country", ""))
        region = _esc(race.get("region", ""))
        event_date = _date_or_dash(race.get("event_date"))
        reg_opens = _date_or_dash(race.get("registration_open_date"))
        reg_deadline = _date_or_dash(race.get("registration_deadline"))
        lottery = _date_or_dash(race.get("lottery_deadline"))
        qual = _date_or_dash(race.get("qualification_deadline"))
        status = _esc(race.get("status", "active"))
        confidence = _esc(race.get("confidence", ""))
        source = race.get("source_url") or race.get("official_url")
        source_cell = f"[link]({source})" if source else ""

        lines.append(
            f"| **{name}** | {city}, {country} | {region} | {event_date} | {reg_opens} | {reg_deadline} | {lottery} | {qual} | {status} | {confidence} | {source_cell} |"
        )

    lines.append("")
    return "\n".join(lines)


def _esc(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def _date_or_dash(value: object) -> str:
    return str(value) if value else "-"
