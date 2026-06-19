from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import RaceResult


CATEGORY_LABELS = {
    "open-to-registration": "Open to Registration",
    "closed-to-registration": "Closed to Registration",
    "match-completed": "Match Completed",
}


def write_outputs(results: list[RaceResult], docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(results),
        "races": [result.to_dict() for result in sorted(results, key=lambda item: (item.region, item.name))],
    }
    (docs_dir / "marathons.md").write_text(render_markdown(payload), encoding="utf-8")


def render_markdown(payload: dict[str, object]) -> str:
    races = payload["races"]
    assert isinstance(races, list)
    generated_at = str(payload["generated_at"])
    count = str(payload["count"])

    buckets: dict[str, list[dict]] = {
        "open-to-registration": [],
        "closed-to-registration": [],
        "match-completed": [],
    }
    for race in races:
        if not isinstance(race, dict):
            continue
        buckets[_race_category(race)].append(race)

    lines = [
        "# Marathon Tracker",
        "",
        f"{count} races tracked. Generated {generated_at} UTC from official race pages where available.",
        "",
    ]

    for cat_key in ("open-to-registration", "closed-to-registration", "match-completed"):
        group = buckets[cat_key]
        if not group:
            continue
        lines.append(f"## {CATEGORY_LABELS[cat_key]} ({len(group)})")
        lines.append("")
        lines.append(
            "| Race | Location | Region | Event Date | Registration Windows | Confidence | Source |"
        )
        lines.append(
            "|------|----------|--------|------------|----------------------|------------|--------|"
        )
        for race in group:
            name = _esc(race.get("name", ""))
            if race.get("year"):
                name = f"{name} ({race['year']})"
            city = _esc(race.get("city", ""))
            country = _esc(race.get("country", ""))
            region = _esc(race.get("region", ""))
            event_date = _date_or_dash(race.get("event_date"))
            
            # Format windows cell
            windows_list = race.get("registration_windows") or []
            windows_cell = _format_windows(windows_list)
            
            confidence = _esc(race.get("confidence", ""))
            source = race.get("source_url") or race.get("official_url")
            source_cell = f"[link]({source})" if source else ""

            lines.append(
                f"| **{name}** | {city}, {country} | {region} | {event_date} | {windows_cell} | {confidence} | {source_cell} |"
            )
        lines.append("")

    return "\n".join(lines)


def _format_windows(windows: list[dict]) -> str:
    if not windows:
        return "-"
        
    def sort_key(w):
        c = w.get("close_date") or ""
        o = w.get("open_date") or ""
        t = w.get("window_type", "")
        return (c, o, t)
        
    sorted_windows = sorted(windows, key=sort_key)
    formatted = []
    for w in sorted_windows:
        w_type = w.get("window_type", "")
        desc = w.get("description") or w_type.replace("-", " ").title()
        op = w.get("open_date")
        cl = w.get("close_date")
        
        desc_esc = _esc(desc)
        if op and cl:
            formatted.append(f"**{desc_esc}**:<br>{op} to {cl}")
        elif cl:
            formatted.append(f"**{desc_esc}**:<br>deadline {cl}")
        elif op:
            formatted.append(f"**{desc_esc}**:<br>opens {op}")
        else:
            formatted.append(f"**{desc_esc}**")
            
    return "<br>".join(formatted)


def _race_category(race: dict) -> str:
    today = datetime.now(timezone.utc).date()

    event = _parse_date(race.get("event_date"))
    if event and event < today:
        return "match-completed"

    windows = race.get("registration_windows") or []
    deadlines = []
    for w in windows:
        cl = _parse_date(w.get("close_date"))
        if cl:
            deadlines.append(cl)

    if deadlines and max(deadlines) < today:
        return "closed-to-registration"

    return "open-to-registration"


def _parse_date(value: object) -> datetime.date | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date()
    except (ValueError, TypeError):
        return None


def _esc(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def _date_or_dash(value: object) -> str:
    return str(value) if value else "-"
