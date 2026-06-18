from __future__ import annotations

import html
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
    (docs_dir / "index.html").write_text(render_html(payload), encoding="utf-8")


def render_html(payload: dict[str, object]) -> str:
    races = payload["races"]
    assert isinstance(races, list)
    rows = "\n".join(render_row(race) for race in races if isinstance(race, dict))
    generated_at = html.escape(str(payload["generated_at"]))
    count = html.escape(str(payload["count"]))
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
    .meta {{ margin: 0; color: var(--muted); max-width: 760px; }}
    main {{ padding: 20px clamp(12px, 3vw, 40px) 40px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; text-transform: uppercase; color: var(--muted); background: #f0f4f8; }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: var(--accent); }}
    .muted {{ color: var(--muted); }}
    .confidence {{ font-weight: 650; }}
    .low, .unknown {{ color: var(--warn); }}
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
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Race</th>
            <th>Location</th>
            <th>Region</th>
            <th>Event Date</th>
            <th>Registration Opens</th>
            <th>Registration Deadline</th>
            <th>Lottery Deadline</th>
            <th>Qualification Deadline</th>
            <th>Confidence</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""


def render_row(race: dict[str, object]) -> str:
    confidence = esc(race.get("confidence"))
    source = race.get("source_url") or race.get("official_url")
    source_html = f'<a href="{esc(source)}">official page</a>' if source else ""
    return f"""          <tr>
            <td><strong>{esc(race.get("name"))}</strong><br><span class="muted">{esc(race.get("notes"))}</span></td>
            <td>{esc(race.get("city"))}, {esc(race.get("country"))}</td>
            <td>{esc(race.get("region"))}</td>
            <td>{date_or_dash(race.get("event_date"))}</td>
            <td>{date_or_dash(race.get("registration_open_date"))}</td>
            <td>{date_or_dash(race.get("registration_deadline"))}</td>
            <td>{date_or_dash(race.get("lottery_deadline"))}</td>
            <td>{date_or_dash(race.get("qualification_deadline"))}</td>
            <td class="confidence {confidence}">{confidence}</td>
            <td>{source_html}</td>
          </tr>"""


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def date_or_dash(value: object) -> str:
    return esc(value) if value else '<span class="muted">-</span>'

