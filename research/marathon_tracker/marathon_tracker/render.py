from __future__ import annotations

import json
import re
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
    
    # Filter to only medium or high confidence races
    published_results = [r for r in results if r.confidence in ("medium", "high")]
    
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(published_results),
        "races": [result.to_dict() for result in sorted(published_results, key=lambda item: (item.region, item.name))],
    }
    
    (docs_dir / "marathons.md").write_text(render_markdown(payload), encoding="utf-8")
    (docs_dir / "index.html").write_text(render_html(payload), encoding="utf-8")


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
            "| Race | Distance | Location | Region | Event Date | Registration Windows | Confidence | Source |"
        )
        lines.append(
            "|------|----------|----------|--------|------------|----------------------|------------|--------|"
        )
        for race in group:
            name = _esc(race.get("name", ""))
            event_date_val = race.get("event_date")
            if event_date_val:
                name = f"{name} ({str(event_date_val)[:4]})"
            
            city = _esc(race.get("city", ""))
            state = _esc(race.get("state_province_name") or race.get("state_province", ""))
            country = _esc(race.get("country", ""))
            location_cell = f"{city}, {state}, {country}" if state else f"{city}, {country}"
            
            region = _esc(race.get("region", ""))
            event_date = _date_or_dash(race.get("event_date"))
            
            # Format windows cell
            windows_list = race.get("registration_windows") or []
            windows_cell = _format_windows(windows_list)
            
            confidence = _esc(race.get("confidence", ""))
            source = race.get("source_url") or race.get("official_url")
            source_cell = f"[link]({source})" if source else ""

            distance_val = race.get("distance", "marathon")
            distance_label = "Half Marathon" if distance_val == "half-marathon" else "Marathon"

            lines.append(
                f"| **{name}** | {distance_label} | {location_cell} | {region} | {event_date} | {windows_cell} | {confidence} | {source_cell} |"
            )
        lines.append("")

    lines.append("*Only races with medium or high confidence are shown. See the database for all tracked races.*")
    return "\n".join(lines)


def render_html(payload: dict[str, object]) -> str:
    races = payload["races"]
    assert isinstance(races, list)
    rows = "\n".join(render_row(race) for race in races if isinstance(race, dict))
    generated_at = _esc(str(payload["generated_at"]))
    count = _esc(str(payload["count"]))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Marathon Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5f6b7a;
      --line: #d7dee8;
      --surface: #f7f9fb;
      --accent: #0b6bcb;
      --warn: #8a5a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #ffffff;
    }}
    header {{
      padding: 28px clamp(16px, 4vw, 48px) 18px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 42px); letter-spacing: 0; }}
    .meta {{ margin: 0 0 16px; color: var(--muted); max-width: 760px; }}
    main {{ padding: 20px clamp(12px, 3vw, 40px) 40px; }}
    .filters {{ margin-bottom: 20px; display: flex; gap: 12px; align-items: center; }}
    .filters label {{ font-weight: 600; font-size: 14px; color: var(--muted); }}
    .filters select {{
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #ffffff;
      font-size: 14px;
      color: var(--ink);
      cursor: pointer;
      outline: none;
    }}
    .filters select:focus {{ border-color: var(--accent); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; text-transform: uppercase; color: var(--muted); background: #f0f4f8; }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: var(--accent); }}
    .muted {{ color: var(--muted); }}
    .confidence {{ font-weight: 650; }}
    .low, .unknown {{ color: var(--warn); }}
    .footer-note {{ margin-top: 20px; font-size: 13px; color: var(--muted); }}
    @media (max-width: 720px) {{
      header {{ padding-top: 20px; }}
      th, td {{ padding: 9px 10px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Marathon Tracker</h1>
    <p class="meta">{count} races tracked. Generated {generated_at} UTC from official race pages where available.</p>
  </header>
  <main>
    <div class="filters">
      <label for="distance-filter">Distance:</label>
      <select id="distance-filter" onchange="filterRaces()">
        <option value="all">All Distances</option>
        <option value="marathon">Marathon</option>
        <option value="half-marathon">Half Marathon</option>
      </select>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Race</th>
            <th>Distance</th>
            <th>Location</th>
            <th>Region</th>
            <th>Event Date</th>
            <th>Registration Windows</th>
            <th>Confidence</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
    <p class="footer-note">*Only races with medium or high confidence are shown. See the database for all tracked races.</p>
  </main>
  <script>
    function filterRaces() {{
      const val = document.getElementById('distance-filter').value;
      const rows = document.querySelectorAll('tbody tr');
      rows.forEach(row => {{
        const dist = row.getAttribute('data-distance');
        if (val === 'all' || dist === val) {{
          row.style.display = '';
        }} else {{
          row.style.display = 'none';
        }}
      }});
    }}
  </script>
</body>
</html>
"""


def render_row(race: dict[str, object]) -> str:
    import html
    def esc_html(v: object) -> str:
        return html.escape("" if v is None else str(v), quote=True)

    confidence = esc_html(race.get("confidence"))
    dist = esc_html(race.get("distance", "marathon"))
    dist_label = "Half Marathon" if dist == "half-marathon" else "Marathon"
    
    name_str = esc_html(race.get("name", ""))
    event_date_val = race.get("event_date")
    if event_date_val:
        name_str = f"{name_str} ({str(event_date_val)[:4]})"
        
    notes_str = esc_html(race.get("notes", ""))
    notes_html = f'<br><span class="muted">{notes_str}</span>' if notes_str else ''
    
    city = esc_html(race.get("city", ""))
    state = esc_html(race.get("state_province_name") or race.get("state_province", ""))
    country = esc_html(race.get("country", ""))
    location_str = f"{city}, {state}, {country}" if state else f"{city}, {country}"
    
    region = esc_html(race.get("region", ""))
    event_date = esc_html(race.get("event_date")) if race.get("event_date") else '<span class="muted">-</span>'
    
    windows_list = race.get("registration_windows") or []
    windows_formatted = []
    
    def sort_key(w):
        c = w.get("close_date") or ""
        o = w.get("open_date") or ""
        t = w.get("window_type", "")
        return (c, o, t)
        
    for w in sorted(windows_list, key=sort_key):
        w_type = w.get("window_type", "")
        desc = w.get("description") or w_type.replace("-", " ").title()
        op = w.get("open_date")
        cl = w.get("close_date")
        
        desc_esc = esc_html(desc)
        if op and cl:
            windows_formatted.append(f"**{desc_esc}**:<br>{op} to {cl}")
        elif cl:
            windows_formatted.append(f"**{desc_esc}**:<br>deadline {cl}")
        elif op:
            windows_formatted.append(f"**{desc_esc}**:<br>opens {op}")
        else:
            windows_formatted.append(f"**{desc_esc}**")
            
    windows_cell = "<br>".join(windows_formatted) if windows_formatted else '<span class="muted">-</span>'
    windows_cell = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", windows_cell)
    
    source = race.get("source_url") or race.get("official_url")
    source_html = f'<a href="{esc_html(source)}">official page</a>' if source else ""
    
    return f"""          <tr data-distance="{dist}">
            <td><strong>{name_str}</strong>{notes_html}</td>
            <td>{dist_label}</td>
            <td>{location_str}</td>
            <td>{region}</td>
            <td>{event_date}</td>
            <td>{windows_cell}</td>
            <td class="confidence {confidence}">{confidence}</td>
            <td>{source_html}</td>
          </tr>"""


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
