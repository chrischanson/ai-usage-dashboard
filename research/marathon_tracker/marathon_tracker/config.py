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
        SELECT r.id, r.name, ro.distance, l.city, l.state_province, s.name AS state_province_name, l.country_name, c.region_name, ou.url as official_url
        FROM race_races r
        JOIN loc_locations l ON r.location_id = l.id
        JOIN loc_countries c ON l.country_name = c.name
        JOIN race_offerings ro ON r.id = ro.race_id
        JOIN race_official_urls ou ON r.official_url_id = ou.id
        LEFT JOIN loc_subdivisions s ON l.country_name = s.country_name AND l.state_province = s.code
    """)
    
    races = []
    for row in cursor.fetchall():
        races.append(Race(
            id=row["id"],
            name=row["name"],
            distance=row["distance"],
            city=row["city"],
            state_province=row["state_province"],
            state_province_name=row["state_province_name"],
            country=row["country_name"],
            region=row["region_name"],
            official_url=row["official_url"]
        ))
    conn.close()
    return races


def load_previous_output(path: Path = DEFAULT_DB) -> dict[tuple[str, str, int | None], RaceResult] | None:
    if not path.exists():
        return None
    
    from .db import init_db
    conn = get_connection(path)
    init_db(conn)
    cursor = conn.cursor()
    
    # 1. Fetch all registration windows and group by event_id
    cursor.execute("""
        SELECT rw.event_id, rw.window_type, rw.description, rw.open_date, rw.close_date, ou.url as official_url
        FROM race_registration_windows rw
        LEFT JOIN race_official_urls ou ON rw.official_url_id = ou.id
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
            r.id, r.name, ro.distance, l.city, l.state_province, s.name AS state_province_name, l.country_name, c.region_name,
            ou_off.url as official_url,
            e.id as event_id, e.event_date, e.status,
            cl.timestamp as extracted_at,
            json_extract(cl.details, '$.source_url') as source_url,
            json_extract(cl.details, '$.extraction_method') as extraction_method,
            json_extract(cl.details, '$.confidence') as confidence,
            json_extract(cl.details, '$.notes') as notes,
            json_extract(cl.details, '$.raw_evidence') as raw_evidence
        FROM race_races r
        JOIN loc_locations l ON r.location_id = l.id
        JOIN loc_countries c ON l.country_name = c.name
        JOIN race_offerings ro ON r.id = ro.race_id
        JOIN race_official_urls ou_off ON r.official_url_id = ou_off.id
        LEFT JOIN loc_subdivisions s ON l.country_name = s.country_name AND l.state_province = s.code
        LEFT JOIN race_events e ON ro.id = e.race_offering_id
        LEFT JOIN change_log cl ON cl.id = (
            SELECT id FROM change_log
            WHERE table_name = 'race_events'
              AND action = 'EXTRACT'
              AND record_id = CAST(e.id AS TEXT)
            ORDER BY id DESC LIMIT 1
        )
    """)
    
    results = {}
    for row in cursor.fetchall():
        # Even if event_date is NULL, we load it
        event_date = row["event_date"]
        year = None
        if event_date:
            try:
                year = int(event_date[:4])
            except (ValueError, TypeError):
                pass
            
        try:
            raw_evidence = json.loads(row["raw_evidence"]) if row["raw_evidence"] else []
        except json.JSONDecodeError:
            raw_evidence = []
            
        ev_id = row["event_id"]
        windows = windows_by_event.get(ev_id, []) if ev_id is not None else []
            
        results[(row["id"], row["distance"], year)] = RaceResult(
            id=row["id"],
            name=row["name"],
            distance=row["distance"],
            city=row["city"],
            state_province=row["state_province"],
            state_province_name=row["state_province_name"],
            country=row["country_name"],
            region=row["region_name"],
            official_url=row["official_url"],
            event_date=event_date,
            year=year,
            registration_windows=windows,
            source_url=row["source_url"],
            extracted_at=row["extracted_at"] or "",
            extraction_method=row["extraction_method"] or "seed",
            confidence=row["confidence"] or "unknown",
            status=row["status"] or "active",
            notes=row["notes"] or "",
            raw_evidence=raw_evidence
        )
    
    conn.close()
    return results

def _get_or_create_location(cursor, city: str, state_province: str | None, country: str) -> int:
    if state_province:
        # Ensure country exists in loc_countries first
        cursor.execute("SELECT 1 FROM loc_countries WHERE name = ?", (country,))
        if not cursor.fetchone():
            cursor.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES (?, 'Unknown')", (country,))

        # Ensure subdivision exists in loc_subdivisions
        cursor.execute(
            "INSERT OR IGNORE INTO loc_subdivisions (code, country_name, name) VALUES (?, ?, ?)",
            (state_province, country, state_province)
        )

        cursor.execute(
            "SELECT id FROM loc_locations WHERE city = ? AND state_province = ? AND country_name = ?",
            (city, state_province, country)
        )
        row = cursor.fetchone()
        if row:
            return row["id"]
    else:
        cursor.execute(
            "SELECT id, state_province FROM loc_locations WHERE city = ? AND country_name = ?",
            (city, country)
        )
        rows = cursor.fetchall()
        if len(rows) == 1:
            return rows[0]["id"]
        elif len(rows) > 1:
            for r in rows:
                if not r["state_province"]:
                    return r["id"]
                    
    cursor.execute(
        "INSERT INTO loc_locations (city, state_province, country_name) VALUES (?, ?, ?)",
        (city, state_province, country)
    )
    return cursor.lastrowid


def save_races(races: list[Race], path: Path = DEFAULT_DB) -> None:
    from .db import init_db
    conn = get_connection(path)
    init_db(conn)
    cursor = conn.cursor()
    
    count = 0
    for race in races:
        try:
            # 1. Ensure region and country exist in loc_countries lookup
            cursor.execute("INSERT OR IGNORE INTO loc_regions (name) VALUES (?)", (race.region,))
            cursor.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES (?, ?)", (race.country, race.region))

            # 2. Get or create location
            location_id = _get_or_create_location(cursor, race.city, race.state_province, race.country)

            # 3. Resolve URL ID
            cursor.execute("INSERT OR IGNORE INTO race_official_urls (url) VALUES (?)", (race.official_url,))
            cursor.execute("SELECT id FROM race_official_urls WHERE url = ?", (race.official_url,))
            official_url_id = cursor.fetchone()["id"]
            
            # 4. Insert into race_races referencing location and URL ID
            cursor.execute(
                """
                INSERT OR IGNORE INTO race_races (id, name, location_id, official_url_id)
                VALUES (?, ?, ?, ?)
                """,
                (race.id, race.name, location_id, official_url_id)
            )

            # 5. Insert into race_offerings
            cursor.execute(
                """
                INSERT OR IGNORE INTO race_offerings (race_id, distance)
                VALUES (?, ?)
                """,
                (race.id, race.distance)
            )
            count += 1
        except Exception: # likely IntegrityError or other
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
        # Resolve location, country, region
        cursor.execute("INSERT OR IGNORE INTO loc_regions (name) VALUES (?)", (result.region,))
        cursor.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES (?, ?)", (result.country, result.region))
        
        location_id = _get_or_create_location(cursor, result.city, result.state_province, result.country)

        cursor.execute("INSERT OR IGNORE INTO race_official_urls (url) VALUES (?)", (result.official_url,))
        cursor.execute("SELECT id FROM race_official_urls WHERE url=?", (result.official_url,))
        official_url_id = cursor.fetchone()["id"]

        cursor.execute(
            "INSERT OR IGNORE INTO race_races (id, name, location_id, official_url_id) VALUES (?, ?, ?, ?)",
            (result.id, result.name, location_id, official_url_id)
        )

        cursor.execute(
            "INSERT OR IGNORE INTO race_offerings (race_id, distance) VALUES (?, ?)",
            (result.id, result.distance)
        )

        # Retrieve race_offering_id
        cursor.execute(
            "SELECT id FROM race_offerings WHERE race_id = ? AND distance = ?",
            (result.id, result.distance)
        )
        race_offering_id = cursor.fetchone()["id"]

        # Try to find an existing event for this offering in the same year or with NULL date
        year_str = None
        if result.event_date:
            year_str = result.event_date[:4] # 'YYYY'
            
        event_id = None
        
        # 1. Look for exact date match
        if result.event_date:
            cursor.execute(
                "SELECT id FROM race_events WHERE race_offering_id = ? AND event_date = ?",
                (race_offering_id, result.event_date)
            )
            row = cursor.fetchone()
            if row:
                event_id = row["id"]
                
        # 2. Look for same year match
        if not event_id and year_str:
            cursor.execute(
                """
                SELECT id FROM race_events 
                WHERE race_offering_id = ? 
                  AND substr(event_date, 1, 4) = ?
                """,
                (race_offering_id, year_str)
            )
            row = cursor.fetchone()
            if row:
                event_id = row["id"]
                
        # 3. Look for TBD event (NULL date)
        if not event_id:
            cursor.execute(
                "SELECT id FROM race_events WHERE race_offering_id = ? AND event_date IS NULL",
                (race_offering_id,)
            )
            row = cursor.fetchone()
            if row:
                event_id = row["id"]

        if event_id:
            # Update the event_date and status
            cursor.execute(
                "UPDATE race_events SET event_date = ?, status = ? WHERE id = ?",
                (result.event_date, result.status or "active", event_id)
            )
        else:
            # Insert new event
            cursor.execute(
                """
                INSERT INTO race_events (race_offering_id, event_date, status)
                VALUES (?, ?, ?)
                """,
                (race_offering_id, result.event_date, result.status or "active")
            )
            event_id = cursor.lastrowid
        
        # Sync registration windows
        cursor.execute("DELETE FROM race_registration_windows WHERE event_id = ?", (event_id,))
        for w in result.registration_windows:
            official_url_id_window = None
            if w.official_url:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO race_official_urls (url)
                    VALUES (?)
                    """,
                    (w.official_url,)
                )
                cursor.execute(
                    """
                    SELECT id FROM race_official_urls WHERE url = ?
                    """,
                    (w.official_url,)
                )
                row_url = cursor.fetchone()
                if row_url:
                    official_url_id_window = row_url["id"]

            cursor.execute(
                """
                INSERT OR IGNORE INTO race_registration_windows (event_id, window_type, description, open_date, close_date, official_url_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, w.window_type, w.description, w.open_date, w.close_date, official_url_id_window)
            )
        
        confidence = result.confidence or "unknown"
        cursor.execute(
            """
            INSERT INTO change_log (timestamp, table_name, action, record_id, details)
            VALUES (?, 'race_events', 'EXTRACT', ?, ?)
            """,
            (
                result.extracted_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%fZ'),
                str(event_id),
                json.dumps({
                    "source_url": result.source_url,
                    "extraction_method": result.extraction_method or "seed",
                    "confidence": confidence,
                    "notes": result.notes or "",
                    "raw_evidence": result.raw_evidence or []
                })
            )
        )
        
    conn.commit()
    conn.close()
