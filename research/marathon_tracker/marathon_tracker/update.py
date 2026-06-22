import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_DB, DEFAULT_DOCS_DIR, load_previous_output, load_races, save_races
from .discover import discover_races, merge_races
from .extract import extract_dates
from .fetch import check_url, fetch_text
from .models import Race, RaceResult
from .render import write_outputs
from .scrapers import get_scraper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update marathon race date research outputs.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to SQLite database.")
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
    parser.add_argument("--race-id", type=str, help="Update only the specified race ID.")
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
    # If the event year is in the past, it never needs refresh
    current_year = datetime.now(timezone.utc).year
    event_year = None
    if result.event_date:
        try:
            event_year = datetime.fromisoformat(result.event_date).year
        except (ValueError, TypeError):
            pass
            
    if event_year and event_year < current_year:
        return False
        
    # Check if event date is soon (within 90 days)
    event_days = _days_until(result.event_date)
    if event_days is not None and event_days < 0:
        return False
        
    event_soon = event_days is not None and 0 <= event_days <= 90
    
    # Check if any registration window deadline is soon
    window_days = [_days_until(w.close_date) for w in result.registration_windows]
    window_soon = any(d is not None and 0 <= d <= 90 for d in window_days)
    
    milestone_soon = event_soon or window_soon
    
    # Incomplete data: event is in the future/TBD but we have no registration windows
    missing_milestones = (
        (event_days is None or event_days > 0)
        and len(result.registration_windows) == 0
    )
    
    if not result.extracted_at or result.extraction_method == "carried-over":
        stale = True
    else:
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
    previous = load_previous_output(args.db)

    curated = load_races(args.db)
    if args.race_id:
        curated = [r for r in curated if r.id == args.race_id]
        if not curated:
            print(f"error: race_id '{args.race_id}' not found in database.", file=sys.stderr)
            return 1

    curated_map = {(r.id, r.distance): r for r in curated}

    discovered: list[Race] = []
    if not no_network and args.discover and not args.race_id:
        sources = ("world-athletics", "wikipedia") if args.discover_source == "all" else (args.discover_source,)
        discovered = discover_races(sources)

    races = merge_races(curated, discovered, previous=previous)

    new_discoveries = [d for d in discovered if (d.id, d.distance) not in curated_map]
    if new_discoveries and not no_network:
        save_races(new_discoveries, args.db)

    if args.limit:
        races = races[: args.limit]

    print(f"phase-a: {len(curated)} curated, {len(discovered)} discovered, {len(races)} total")

    races_by_key = {(r.id, r.distance): r for r in races}

    # ── Phase B: Prioritize ─────────────────────────────────────────
    results: list[RaceResult] = []
    refresh_count = 0
    carry_count = 0

    current_year = today.year

    for race in races:
        # Find all matching events in previous
        race_events_in_prev = []
        if previous:
            for (r_id, dist, ev_date), prev_result in previous.items():
                if r_id == race.id and dist == race.distance:
                    race_events_in_prev.append(prev_result)

        has_current_or_future = False
        for prev in race_events_in_prev:
            event_year = None
            if prev.event_date:
                try:
                    event_year = datetime.fromisoformat(prev.event_date).year
                except ValueError:
                    pass
            if event_year is None or event_year >= current_year:
                has_current_or_future = True

        if race_events_in_prev:
            for prev in race_events_in_prev:
                result = RaceResult.from_race(race, distance=race.distance)
                result.extracted_at = prev.extracted_at
                result.extraction_method = prev.extraction_method
                result.confidence = prev.confidence
                result.status = prev.status
                result.notes = prev.notes
                result.raw_evidence = list(prev.raw_evidence)
                result.event_date = prev.event_date
                result.registration_windows = list(prev.registration_windows)

                needs = True if args.race_id else (_needs_refresh(result) if not no_network else False)

                if needs:
                    result.status = "active"
                    refresh_count += 1
                else:
                    if result.status not in ("active", "stale", "carried-over"):
                        result.status = "carried-over"
                    if result.extraction_method not in ("llm", "regex", "seed"):
                        result.extraction_method = "carried-over"
                    carry_count += 1

                results.append(result)
        
        # Seed a new event if none exists, or if only past events exist
        if not has_current_or_future:
            result = RaceResult.from_race(race, distance=race.distance)
            needs = True if args.race_id else (_needs_refresh(result) if not no_network else False)

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

            race_obj = races_by_key.get((result.id, result.distance))
            if not race_obj:
                continue

            scraper = get_scraper(result.id)
            if scraper:
                print(f"Using custom scraper for {result.id}")
                fresh = scraper(race_obj)
            else:
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
                    fresh = extract_dates(race_obj, page_text, source_url=url)
                else:
                    result.status = "stale"
                    result.confidence = "low"
                    result.notes = "Page fetch returned no content; last known data preserved."
                    continue

            # Update dates and details
            result.event_date = fresh.event_date
            result.registration_windows = list(fresh.registration_windows)
            result.extraction_method = fresh.extraction_method
            result.confidence = fresh.confidence
            result.notes = fresh.notes
            result.raw_evidence = list(fresh.raw_evidence)
            if fresh.source_url and not result.source_url:
                result.source_url = fresh.source_url
            result.extracted_at = today.isoformat(timespec="seconds")

    refreshed = sum(1 for r in results if r.extraction_method not in ("carried-over",))
    print(f"phase-c: {refreshed} refreshed, {carry_count} carried over")

    from .config import save_race_results
    save_race_results(results)
    write_outputs(results, args.docs_dir)
    print(f"wrote {len(results)} races to {args.docs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
