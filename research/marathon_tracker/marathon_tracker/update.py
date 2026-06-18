from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG, DEFAULT_DOCS_DIR, load_previous_output, load_races, save_races
from .discover import discover_races, merge_races
from .extract import DATE_FIELDS, extract_dates
from .fetch import check_url, fetch_text
from .models import Race, RaceResult
from .render import write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update marathon race date research outputs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to race config JSON.")
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS_DIR, help="Static output directory.")
    parser.add_argument("--no-network", action="store_true", help="Render without fetching or discovering.")
    parser.add_argument("--limit", type=int, default=0, help="Limit races for testing.")
    parser.add_argument(
        "--discover", action=argparse.BooleanOptionalAction, default=True,
        help="Discover new races from external directories.",
    )
    parser.add_argument(
        "--discover-source", choices=["world-athletics", "wikipedia", "all"], default="world-athletics",
        help="Source for auto-discovery.",
    )
    return parser


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_until(date_str: str | None) -> float | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - _now()).total_seconds() / 86400
    except (ValueError, TypeError):
        return None


def _needs_refresh(result: RaceResult) -> bool:
    days = [_days_until(getattr(result, f)) for f in DATE_FIELDS]
    milestone_soon = any(d is not None and 0 <= d <= 90 for d in days)
    missing_milestones = (
        _days_until(result.event_date) is not None
        and _days_until(result.event_date) > 0
        and any(getattr(result, f) is None for f in DATE_FIELDS)
    )
    stale = result.extracted_at is not None
    if stale:
        try:
            extracted = datetime.fromisoformat(result.extracted_at)
            if extracted.tzinfo is None:
                extracted = extracted.replace(tzinfo=timezone.utc)
            stale = (_now() - extracted).total_seconds() > 30 * 86400
        except (ValueError, TypeError):
            stale = True
    return milestone_soon or missing_milestones or stale


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    no_network = args.no_network or False
    today = _now()

    # ── Phase A: Load state + Discover ──────────────────────────────
    previous: dict[str, RaceResult] | None = None
    if not no_network:
        previous = load_previous_output()

    curated = load_races(args.config)
    curated_map: dict[str, Race] = {r.id: r for r in curated}

    discovered: list[Race] = []
    if not no_network and args.discover:
        sources = ("world-athletics", "wikipedia") if args.discover_source == "all" else (args.discover_source,)
        discovered = discover_races(sources)

    races = merge_races(curated, discovered)

    new_discoveries = [d for d in discovered if d.id not in curated_map]
    if new_discoveries and not no_network:
        save_races(new_discoveries, args.config)

    if args.limit:
        races = races[: args.limit]

    print(f"phase-a: {len(curated)} curated, {len(discovered)} discovered, {len(races)} total")

    races_by_id: dict[str, Race] = {r.id: r for r in races}

    # ── Phase B: Prioritize ─────────────────────────────────────────
    results: list[RaceResult] = []
    refresh_count = 0
    carry_count = 0

    for race in races:
        result = RaceResult.from_race(race)

        if previous and race.id in previous:
            prev = previous[race.id]
            result.extracted_at = prev.extracted_at
            result.extraction_method = prev.extraction_method
            result.confidence = prev.confidence
            result.status = prev.status
            result.notes = prev.notes
            result.raw_evidence = list(prev.raw_evidence)
            for f in DATE_FIELDS:
                if getattr(result, f) is None:
                    setattr(result, f, getattr(prev, f))

        needs = _needs_refresh(result) if not no_network else False

        if needs:
            result.status = "active"
            refresh_count += 1
        else:
            result.status = "carried-over"
            result.extraction_method = "carried-over"
            carry_count += 1

        results.append(result)

    print(f"phase-b: {refresh_count} to refresh, {carry_count} carried over")

    # ── Phase C: Refresh ────────────────────────────────────────────
    if not no_network:
        for result in results:
            if result.status != "active":
                continue

            url = result.source_url or result.official_url
            if not url:
                result.status = "stale"
                result.confidence = "low"
                result.notes = "No source URL available for this race."
                continue

            reachable, error = check_url(url)
            if not reachable:
                result.status = "stale"
                result.confidence = "low"
                result.notes = f"Source URL returned {error}; last known data preserved."
                continue

            page_text = None
            try:
                page_text = fetch_text(url)
            except RuntimeError as exc:
                print(f"warning: could not fetch {url}: {exc}", file=sys.stderr)

            if page_text:
                race_obj = races_by_id.get(result.id)
                if not race_obj:
                    continue
                fresh = extract_dates(race_obj, page_text)
                result.event_date = fresh.event_date
                result.registration_open_date = fresh.registration_open_date
                result.registration_deadline = fresh.registration_deadline
                result.lottery_deadline = fresh.lottery_deadline
                result.qualification_deadline = fresh.qualification_deadline
                result.extraction_method = fresh.extraction_method
                result.confidence = fresh.confidence
                result.notes = fresh.notes
                result.raw_evidence = list(fresh.raw_evidence)
            else:
                result.status = "stale"
                result.confidence = "low"
                result.notes = "Page fetch returned no content; last known data preserved."

            result.extracted_at = today.isoformat(timespec="seconds")

    refreshed = sum(1 for r in results if r.extraction_method not in ("carried-over",))
    print(f"phase-c: {refreshed} refreshed, {carry_count} carried over")

    write_outputs(results, args.docs_dir)
    print(f"wrote {len(results)} races to {args.docs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
