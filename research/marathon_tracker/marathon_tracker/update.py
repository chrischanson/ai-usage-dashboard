import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_DB, DEFAULT_DOCS_DIR, load_previous_output, load_races, save_races, save_race_results
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
    parser.add_argument(
        "--plan", action="store_true",
        help="Plan mode: Output what updates and resolutions will be performed, without executing them or modifying the database.",
    )
    parser.add_argument(
        "--llm-mode", choices=["api", "agy", "opencode", "auto"], default="auto",
        help="LLM execution mode. 'auto' selects LLM_API_KEY, then agy CLI, then opencode CLI.",
    )
    parser.add_argument(
        "--reset-db", action="store_true",
        help=(
            "Delete the existing database before running, starting from a clean state. "
            "WARNING: all previously extracted race data will be permanently lost. "
            "A backup is saved alongside the original file before deletion."
        ),
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


def _get_refresh_reason(result: RaceResult) -> str | None:
    # If the event year is in the past, it never needs refresh
    current_year = datetime.now(timezone.utc).year
    event_year = None
    if result.event_date:
        try:
            event_year = datetime.fromisoformat(result.event_date).year
        except (ValueError, TypeError):
            pass
            
    if event_year and event_year < current_year:
        return None
        
    # Check if event date is soon (within 90 days)
    event_days = _days_until(result.event_date)
    if event_days is not None and event_days < 0:
        return None
        
    if event_days is not None and 0 <= event_days <= 90:
        return f"Event date ({result.event_date}) is soon (within {int(event_days)} days)"
        
    # Check if any registration window deadline is soon
    for w in result.registration_windows:
        d = _days_until(w.close_date)
        if d is not None and 0 <= d <= 90:
            return f"Registration window '{w.description or w.window_type}' deadline is soon (within {int(d)} days)"
            
    # Incomplete data: event is in the future/TBD but we have no registration windows
    if (event_days is None or event_days > 0) and len(result.registration_windows) == 0:
        return "Event has no registration windows configured"
        
    # Stale check
    if not result.extracted_at or result.extraction_method == "carried-over":
        return "No previous extraction history or carried-over status"
        
    try:
        extracted = datetime.fromisoformat(result.extracted_at)
        if extracted.tzinfo is None:
            extracted = extracted.replace(tzinfo=timezone.utc)
        diff_days = (_now() - extracted).total_seconds() / 86400
        if diff_days > 30:
            return f"Data is stale (last extracted {int(diff_days)} days ago)"
    except (ValueError, TypeError):
        return "Invalid last extraction timestamp"
        
    return None


def _needs_refresh(result: RaceResult) -> bool:
    return _get_refresh_reason(result) is not None


def _flag_duplicate_event_dates(
    results: list[RaceResult],
    threshold: int = 3,
) -> list[str]:
    """Detect and neutralise suspicious duplicate event_dates across unrelated races.

    If `threshold` or more *distinct* results share the same event_date, it is
    almost certainly a hallucination artifact.  All such results have their
    confidence downgraded to 'low' and their event_date cleared.  Returns the
    list of flagged date strings (empty if nothing was flagged).
    """
    from collections import defaultdict
    date_to_results: dict[str, list[RaceResult]] = defaultdict(list)
    for r in results:
        if r.event_date and r.extraction_method not in ("seed",):
            date_to_results[r.event_date].append(r)

    flagged_dates: list[str] = []
    for date_str, group in date_to_results.items():
        if len(group) >= threshold:
            flagged_dates.append(date_str)
            for r in group:
                r.event_date = None
                r.confidence = "low"
                r.notes = (
                    f"[DUPLICATE DATE GUARD] event_date '{date_str}' was shared by "
                    f"{len(group)} unrelated races — likely a hallucination. "
                    "Date cleared; please re-extract from the official page."
                )
    return flagged_dates


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["LLM_MODE"] = args.llm_mode
    no_network = args.no_network or False
    today = _now()

    # ── Optional: Reset DB ───────────────────────────────────────────
    if getattr(args, "reset_db", False):
        db_path: Path = args.db
        if db_path.exists():
            backup = db_path.with_suffix(".db.bak_reset")
            import shutil
            shutil.copy2(db_path, backup)
            db_path.unlink()
            print(
                f"reset-db: deleted '{db_path}' (backup saved to '{backup}').",
                file=sys.stderr,
            )
        else:
            print(f"reset-db: '{db_path}' does not exist yet; starting fresh.", file=sys.stderr)

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

    # Resolve missing official URLs for races using LLM
    races_to_resolve = [r for r in races if not r.official_url or r.official_url == ""]

    if not no_network and not args.plan:
        from .llm import resolve_official_url
        import dataclasses
        resolved_races = []
        for r in races:
            if not r.official_url or r.official_url == "":
                print(f"Resolving missing official URL for {r.name}...")
                resolved_url = resolve_official_url(r.name)
                if resolved_url:
                    print(f"  -> Resolved to: {resolved_url}")
                    r = dataclasses.replace(r, official_url=resolved_url)
            resolved_races.append(r)
        races = resolved_races

        # Update discovered list with resolved URLs so they save correctly
        resolved_discovered = []
        for d in discovered:
            if not d.official_url or d.official_url == "":
                # Find matching resolved race by ID/distance
                match = next((r for r in races if r.id == d.id and r.distance == d.distance), None)
                if match and match.official_url:
                    d = dataclasses.replace(d, official_url=match.official_url)
            resolved_discovered.append(d)
        discovered = resolved_discovered

    new_discoveries = [d for d in discovered if (d.id, d.distance) not in curated_map]
    if new_discoveries and not no_network and not args.plan:
        save_races(new_discoveries, args.db)

    if args.limit:
        races = races[: args.limit]

    print(f"phase-a: {len(curated)} curated, {len(discovered)} discovered, {len(races)} total")

    races_by_key = {(r.id, r.distance): r for r in races}

    # ── Phase B: Prioritize ─────────────────────────────────────────
    results: list[RaceResult] = []
    refresh_count = 0
    carry_count = 0
    planned_refreshes = []

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

                if args.race_id:
                    needs = (race.id == args.race_id)
                else:
                    needs = (_needs_refresh(result) if not no_network else False)

                if needs:
                    result.status = "active"
                    refresh_count += 1
                    reason = _get_refresh_reason(result) or "Targeted update via --race-id"
                    planned_refreshes.append((race, result, reason))
                else:
                    result.status = "carried-over"
                    result.extraction_method = "carried-over"
                    carry_count += 1

                results.append(result)
        
        # Seed a new event if none exists, or if only past events exist
        if not has_current_or_future:
            result = RaceResult.from_race(race, distance=race.distance)
            if args.race_id:
                needs = (race.id == args.race_id)
            else:
                needs = (_needs_refresh(result) if not no_network else False)

            if needs:
                result.status = "active"
                refresh_count += 1
                reason = _get_refresh_reason(result) or "New event / no current history"
                planned_refreshes.append((race, result, reason))
            else:
                result.status = "carried-over"
                result.extraction_method = "carried-over"
                carry_count += 1

            results.append(result)

    if args.plan:
        print("\n=== MARATHON TRACKER UPDATE PLAN ===")
        print(f"Races loaded: {len(curated)} curated, {len(discovered)} discovered, {len(races)} total")
        print("\n[URL Resolutions]")
        if races_to_resolve:
            for r in races_to_resolve:
                print(f"  - Would resolve official URL for: {r.name} ({r.distance})")
        else:
            print("  - No missing URLs to resolve.")

        print("\n[Planned Refreshes]")
        if planned_refreshes:
            for race, result, reason in planned_refreshes:
                date_label = result.event_date if result.event_date else "TBD"
                print(f"  - Would refresh: {race.name} ({race.distance}) ({date_label})")
                print(f"    Reason: {reason}")
        else:
            print("  - No events scheduled for refresh.")

        print("\n[Carried Over]")
        print(f"  - {carry_count} events would be carried over without modifications.")
        print("====================================\n")
        return 0

    print(f"phase-b: {refresh_count} to refresh, {carry_count} carried over")

    # ── Phase C: Refresh ────────────────────────────────────────────
    refreshed_results = []
    try:
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
                    from urllib.parse import urlparse
                    is_base_domain = False
                    if result.official_url:
                        parsed = urlparse(result.official_url)
                        path = parsed.path.strip("/")
                        if not path or path == "":
                            is_base_domain = True

                    if not result.official_url or result.official_url == "" or is_base_domain:
                        from .llm import resolve_event_webpage
                        event_year = result.year
                        if not event_year and result.event_date:
                            try:
                                event_year = int(result.event_date[:4])
                            except (ValueError, TypeError):
                                pass
                        
                        print(f"Resolving specific event webpage for {result.name}...")
                        resolved_webpage = resolve_event_webpage(result.name, event_year)
                        if resolved_webpage:
                            print(f"  -> Resolved webpage to: {resolved_webpage}")
                            result.official_url = resolved_webpage
                            result.source_url = resolved_webpage
                        elif not result.official_url or result.official_url == "":
                            # Fallback to the race's official website URL
                            result.official_url = race_obj.official_url
                            result.source_url = race_obj.official_url
                    
                    url = result.source_url or result.official_url
                    if not url or url == "":
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
                        if fresh.notes and "429" in fresh.notes:
                            print("ERROR: LLM quota/rate limit exceeded (429). Saving progress and exiting.", file=sys.stderr)
                            break
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
                refreshed_results.append(result)
    finally:
        refreshed = sum(1 for r in results if r.extraction_method not in ("carried-over",))
        print(f"phase-c: {refreshed} refreshed, {carry_count} carried over")

        if refreshed_results:
            print("\n=== MARATHON TRACKER UPDATE SUMMARY ===")
            for r in refreshed_results:
                date_label = r.event_date if r.event_date else "TBD"
                print(f"- [REFRESHED] {r.name} ({r.distance})")
                print(f"  Event Date:   {date_label}")
                print(f"  Official URL: {r.official_url}")
                if r.registration_windows:
                    print("  Registration Windows:")
                    for w in r.registration_windows:
                        desc = w.description or w.window_type.replace("-", " ").title()
                        dates = f"{w.open_date or 'TBD'} to {w.close_date or 'TBD'}"
                        print(f"    * {desc}: {dates}")
                else:
                    print("  Registration Windows: None found")
                print(f"  Confidence:   {r.confidence}")
                if r.notes:
                    print(f"  Notes:        {r.notes}")
                print()
            print("=======================================\n")

        # ── Post-Phase-C: Duplicate-date validation ──────────────────────
        flagged = _flag_duplicate_event_dates(results)
        if flagged:
            print(
                f"warning: duplicate-date guard flagged {len(flagged)} date(s) shared across "
                f"3+ races: {flagged}. Confidence downgraded to 'low' for affected events.",
                file=sys.stderr,
            )

        save_race_results(results)
        write_outputs(results, args.docs_dir)
        print(f"wrote {len(results)} races to {args.docs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
