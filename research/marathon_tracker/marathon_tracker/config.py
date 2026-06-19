import json
from datetime import datetime, timezone
from pathlib import Path

from .db import get_connection
from .models import Race, RaceResult, RegistrationWindow


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "docs" / "marathons.db"
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs"


def load_races(path: Path = DEFAULT_DB) -> list[Race]:
    if not path.exists():
        return []
    
    from .db import init_db
    conn = get_connection(path)
    init_db(conn)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.name, l.city, l.country, l.region, r.official_url, r.registration_url 
        FROM races r
        JOIN locations l ON r.location_id = l.id
    """)
    
    races = []
    for row in cursor.fetchall():
        races.append(Race(
            id=row["id"],
            name=row["name"],
            city=row["city"],
            country=row["country"],
            region=row["region"],
            official_url=row["official_url"],
            registration_url=row["registration_url"]
        ))
    conn.close()
    return races


def load_previous_output(path: Path = DEFAULT_DB) -> dict[tuple[str, int], RaceResult] | None:
    if not path.exists():
        return None
    
    from .db import init_db
    conn = get_connection(path)
    init_db(conn)
    cursor = conn.cursor()
    
    # 1. Fetch all registration windows and group by event_id
    cursor.execute("""
        SELECT rw.event_id, rw.window_type, rw.description, rw.open_date, rw.close_date, ou.url as official_url
        FROM registration_windows rw
        LEFT JOIN official_urls ou ON rw.official_url_id = ou.id
    """)
    windows_by_event: dict[int, list[RegistrationWindow]] = {}
    for row in cursor.fetchall():
        ev_id = row["event_id"]
        window = RegistrationWindow(
            window_type=row["window_type"],
            open_date=row["open_date"],
            close_date=row["close_date"],
            description=row["description"],
            official_url=row["official_url"]
        )
        windows_by_event.setdefault(ev_id, []).append(window)
    
    # Load all events for all races
    cursor.execute("""
        SELECT 
            r.id, r.name, l.city, l.country, l.region, r.official_url, r.registration_url,
            e.id as event_id, e.year, e.event_date, e.status,
            ou.url as source_url, m.extracted_at, m.extraction_method, m.confidence, m.notes, m.raw_evidence
        FROM races r
        JOIN locations l ON r.location_id = l.id
        LEFT JOIN race_events e ON r.id = e.race_id
        LEFT JOIN extraction_metadata m ON m.id = (
            SELECT id FROM extraction_metadata
            WHERE event_id = e.id
            ORDER BY id DESC LIMIT 1
        )
        LEFT JOIN official_urls ou ON m.source_url_id = ou.id
    """)
    
    results = {}
    for row in cursor.fetchall():
        year = row["year"]
        if year is None:
            continue
            
        try:
            raw_evidence = json.loads(row["raw_evidence"]) if row["raw_evidence"] else []
        except json.JSONDecodeError:
            raw_evidence = []
            
        ev_id = row["event_id"]
        windows = windows_by_event.get(ev_id, []) if ev_id is not None else []
            
        results[(row["id"], year)] = RaceResult(
            id=row["id"],
            name=row["name"],
            city=row["city"],
            country=row["country"],
            region=row["region"],
            official_url=row["official_url"],
            registration_url=row["registration_url"],
            event_date=row["event_date"],
            registration_windows=windows,
            source_url=row["source_url"],
            extracted_at=row["extracted_at"] or "",
            extraction_method=row["extraction_method"] or "seed",
            confidence=row["confidence"] or "unknown",
            status=row["status"] or "active",
            notes=row["notes"] or "",
            raw_evidence=raw_evidence,
            year=year
        )
    
    conn.close()
    return results


def save_races(races: list[Race], path: Path = DEFAULT_DB) -> None:
    from .db import init_db
    conn = get_connection(path)
    init_db(conn)
    cursor = conn.cursor()
    
    count = 0
    for race in races:
        try:
            # 1. Insert geography into locations
            cursor.execute(
                """
                INSERT OR IGNORE INTO locations (city, country, region)
                VALUES (?, ?, ?)
                """,
                (race.city, race.country, race.region)
            )
            
            # 2. Get location_id
            cursor.execute(
                "SELECT id FROM locations WHERE city = ? AND country = ?",
                (race.city, race.country)
            )
            location_id = cursor.fetchone()["id"]
            
            # 3. Insert into races referencing the location_id
            cursor.execute(
                """
                INSERT INTO races (id, name, location_id, distance, official_url, registration_url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (race.id, race.name, location_id, "marathon", race.official_url, race.registration_url)
            )
            count += 1
        except Exception: # likely IntegrityError for existing ID
            pass
            
    conn.commit()
    conn.close()
    if count > 0:
        print(f"saved {count} new race(s) to {path}")


def save_race_results(results: list[RaceResult], path: Path = DEFAULT_DB) -> None:
    from .db import init_db
    conn = get_connection(path)
    init_db(conn)
    cursor = conn.cursor()
    
    for result in results:
        # Determine year
        year = result.year
        if not year:
            year = datetime.now(timezone.utc).year
            if result.event_date:
                try:
                    dt = datetime.fromisoformat(result.event_date)
                    year = dt.year
                except ValueError:
                    pass
                
        # Insert or update race_events
        status = result.status or "active"
        cursor.execute(
            """
            INSERT INTO race_events (
                race_id, year, event_date, status
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(race_id, year) DO UPDATE SET
                event_date=excluded.event_date,
                status=excluded.status
            """,
            (
                result.id, year, result.event_date, status
            )
        )
        
        # Get event_id to insert metadata and windows
        cursor.execute("SELECT id FROM race_events WHERE race_id=? AND year=?", (result.id, year))
        row = cursor.fetchone()
        event_id = row["id"]
        
        # Sync registration windows
        cursor.execute("DELETE FROM registration_windows WHERE event_id = ?", (event_id,))
        for w in result.registration_windows:
            official_url_id = None
            if w.official_url:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO official_urls (url)
                    VALUES (?)
                    """,
                    (w.official_url,)
                )
                cursor.execute(
                    """
                    SELECT id FROM official_urls WHERE url = ?
                    """,
                    (w.official_url,)
                )
                row_url = cursor.fetchone()
                if row_url:
                    official_url_id = row_url["id"]

            cursor.execute(
                """
                INSERT OR IGNORE INTO registration_windows (event_id, window_type, description, open_date, close_date, official_url_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, w.window_type, w.description or w.window_type, w.open_date, w.close_date, official_url_id)
            )
        
        source_url_id = None
        if result.source_url:
            cursor.execute(
                """
                INSERT OR IGNORE INTO official_urls (url)
                VALUES (?)
                """,
                (result.source_url,)
            )
            cursor.execute(
                """
                SELECT id FROM official_urls WHERE url = ?
                """,
                (result.source_url,)
            )
            row_url = cursor.fetchone()
            if row_url:
                source_url_id = row_url["id"]

        confidence = result.confidence or "unknown"
        cursor.execute(
            """
            INSERT INTO extraction_metadata (
                event_id, source_url_id, extracted_at, extraction_method, confidence, notes, raw_evidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, source_url_id, result.extracted_at, result.extraction_method,
                confidence, result.notes, json.dumps(result.raw_evidence)
            )
        )
        
    conn.commit()
    conn.close()
