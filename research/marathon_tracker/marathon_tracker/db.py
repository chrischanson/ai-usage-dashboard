import json
import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Returns a configured SQLite connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


import json
import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Returns a configured SQLite connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initializes the database schema."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            state_province TEXT, -- New subdivision field
            country TEXT NOT NULL,
            region TEXT NOT NULL,
            UNIQUE(city, state_province, country)
        );

        CREATE TABLE IF NOT EXISTS event_statuses (
            status TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS confidence_levels (
            level TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS official_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS races (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location_id INTEGER NOT NULL,
            official_url_id INTEGER NOT NULL, -- Normalized URL Reference
            registration_url_id INTEGER,      -- Normalized URL Reference
            FOREIGN KEY(location_id) REFERENCES locations(id),
            FOREIGN KEY(official_url_id) REFERENCES official_urls(id),
            FOREIGN KEY(registration_url_id) REFERENCES official_urls(id)
        );

        CREATE TABLE IF NOT EXISTS race_offerings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id TEXT NOT NULL,
            distance TEXT NOT NULL, -- 'marathon', 'half-marathon', etc.
            FOREIGN KEY(race_id) REFERENCES races(id),
            UNIQUE(race_id, distance)
        );

        CREATE TABLE IF NOT EXISTS race_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_offering_id INTEGER NOT NULL, -- References offering instead of parent race
            year INTEGER NOT NULL,
            event_date TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
            FOREIGN KEY(status) REFERENCES event_statuses(status),
            UNIQUE(race_offering_id, year)
        );

        CREATE TABLE IF NOT EXISTS registration_types (
            type TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS registration_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            window_type TEXT NOT NULL,
            description TEXT,
            open_date TEXT,
            close_date TEXT,
            official_url_id INTEGER,
            FOREIGN KEY(event_id) REFERENCES race_events(id),
            FOREIGN KEY(window_type) REFERENCES registration_types(type),
            FOREIGN KEY(official_url_id) REFERENCES official_urls(id),
            UNIQUE(event_id, window_type, open_date, close_date)
        );

        CREATE TABLE IF NOT EXISTS extraction_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            source_url_id INTEGER,
            extracted_at TEXT,
            extraction_method TEXT,
            confidence TEXT NOT NULL DEFAULT 'unknown',
            notes TEXT,
            raw_evidence TEXT,
            FOREIGN KEY(event_id) REFERENCES race_events(id),
            FOREIGN KEY(source_url_id) REFERENCES official_urls(id),
            FOREIGN KEY(confidence) REFERENCES confidence_levels(level)
        );

        CREATE TABLE IF NOT EXISTS change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            table_name TEXT NOT NULL,
            action TEXT NOT NULL,
            record_id TEXT NOT NULL,
            details TEXT NOT NULL
        );
    """)

    conn.execute("INSERT OR IGNORE INTO event_statuses (status) VALUES ('active'), ('stale'), ('carried-over');")
    conn.execute("INSERT OR IGNORE INTO confidence_levels (level) VALUES ('high'), ('medium'), ('low'), ('unknown');")
    conn.execute("INSERT OR IGNORE INTO registration_types (type) VALUES ('standard'), ('lottery'), ('qualification'), ('charity'), ('invitation'), ('guaranteed-entry');")

    cursor = conn.cursor()

    # Automated schema migrations for existing database
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF;")

    # Drop triggers to prevent schema verification errors during table renames
    conn.execute("DROP TRIGGER IF EXISTS log_races_insert;")
    conn.execute("DROP TRIGGER IF EXISTS log_race_events_insert;")
    conn.execute("DROP TRIGGER IF EXISTS log_race_events_update;")
    conn.execute("DROP TRIGGER IF EXISTS log_registration_windows_insert;")
    conn.execute("DROP TRIGGER IF EXISTS log_registration_windows_delete;")

    # 1. Locations migration: Add state_province subdivision field
    cursor.execute("PRAGMA table_info(locations);")
    loc_cols = [row["name"] for row in cursor.fetchall()]
    if "state_province" not in loc_cols:
        cursor.execute("ALTER TABLE locations RENAME TO locations_old;")
        conn.execute("""
            CREATE TABLE locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                state_province TEXT,
                country TEXT NOT NULL,
                region TEXT NOT NULL,
                UNIQUE(city, state_province, country)
            );
        """)
        conn.execute("""
            INSERT INTO locations (id, city, state_province, country, region)
            SELECT id, city, NULL, country, region FROM locations_old;
        """)
        conn.execute("DROP TABLE locations_old;")

    # 2 & 3. Races table migration to normalize URLs and remove distance
    cursor.execute("PRAGMA table_info(races);")
    race_cols = [row["name"] for row in cursor.fetchall()]
    if "official_url_id" not in race_cols:
        # Save all unique URLs to official_urls
        conn.execute("""
            INSERT OR IGNORE INTO official_urls (url)
            SELECT DISTINCT official_url FROM races WHERE official_url IS NOT NULL;
        """)
        conn.execute("""
            INSERT OR IGNORE INTO official_urls (url)
            SELECT DISTINCT registration_url FROM races WHERE registration_url IS NOT NULL AND registration_url != '';
        """)

        cursor.execute("ALTER TABLE races RENAME TO races_old;")
        conn.execute("""
            CREATE TABLE races (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                official_url_id INTEGER NOT NULL,
                registration_url_id INTEGER,
                FOREIGN KEY(location_id) REFERENCES locations(id),
                FOREIGN KEY(official_url_id) REFERENCES official_urls(id),
                FOREIGN KEY(registration_url_id) REFERENCES official_urls(id)
            );
        """)
        # Insert races mapping URLs to official_urls IDs
        conn.execute("""
            INSERT INTO races (id, name, location_id, official_url_id, registration_url_id)
            SELECT 
                ro.id, 
                ro.name, 
                ro.location_id,
                (SELECT id FROM official_urls WHERE url = ro.official_url),
                (SELECT id FROM official_urls WHERE url = ro.registration_url)
            FROM races_old ro;
        """)

        # 4. Race offerings creation and populating
        conn.execute("DROP TABLE IF EXISTS race_offerings;")
        conn.execute("""
            CREATE TABLE race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES races(id),
                UNIQUE(race_id, distance)
            );
        """)
        conn.execute("""
            INSERT OR IGNORE INTO race_offerings (race_id, distance)
            SELECT id, IFNULL(distance, 'marathon') FROM races_old;
        """)

        # 5. Race events migration to reference race_offering_id instead of race_id
        cursor.execute("PRAGMA table_info(race_events);")
        re_cols = [row["name"] for row in cursor.fetchall()]
        if "race_offering_id" not in re_cols:
            cursor.execute("ALTER TABLE race_events RENAME TO race_events_old;")
            
            conn.execute("ALTER TABLE registration_windows RENAME TO registration_windows_old;")
            conn.execute("ALTER TABLE extraction_metadata RENAME TO extraction_metadata_old;")
            
            conn.execute("""
                CREATE TABLE race_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_offering_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    event_date TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
                    FOREIGN KEY(status) REFERENCES event_statuses(status),
                    UNIQUE(race_offering_id, year)
                );
            """)
            conn.execute("""
                INSERT INTO race_events (id, race_offering_id, year, event_date, status)
                SELECT 
                    reo.id, 
                    ro.id, 
                    reo.year, 
                    reo.event_date, 
                    reo.status
                FROM race_events_old reo
                JOIN race_offerings ro ON reo.race_id = ro.race_id AND ro.distance = 'marathon';
            """)
            
            conn.execute("""
                CREATE TABLE registration_windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    window_type TEXT NOT NULL,
                    description TEXT,
                    open_date TEXT,
                    close_date TEXT,
                    official_url_id INTEGER,
                    FOREIGN KEY(event_id) REFERENCES race_events(id),
                    FOREIGN KEY(window_type) REFERENCES registration_types(type),
                    FOREIGN KEY(official_url_id) REFERENCES official_urls(id),
                    UNIQUE(event_id, window_type, open_date, close_date)
                );
            """)
            
            conn.execute("""
                CREATE TABLE extraction_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    source_url_id INTEGER,
                    extracted_at TEXT,
                    extraction_method TEXT,
                    confidence TEXT NOT NULL DEFAULT 'unknown',
                    notes TEXT,
                    raw_evidence TEXT,
                    FOREIGN KEY(event_id) REFERENCES race_events(id),
                    FOREIGN KEY(source_url_id) REFERENCES official_urls(id),
                    FOREIGN KEY(confidence) REFERENCES confidence_levels(level)
                );
            """)
            
            conn.execute("""
                INSERT INTO registration_windows (id, event_id, window_type, description, open_date, close_date, official_url_id)
                SELECT id, event_id, window_type, description, open_date, close_date, official_url_id
                FROM registration_windows_old;
            """)
            conn.execute("""
                INSERT INTO extraction_metadata (id, event_id, source_url_id, extracted_at, extraction_method, confidence, notes, raw_evidence)
                SELECT id, event_id, source_url_id, extracted_at, extraction_method, confidence, notes, raw_evidence
                FROM extraction_metadata_old;
            """)
            
            conn.execute("DROP TABLE registration_windows_old;")
            conn.execute("DROP TABLE extraction_metadata_old;")
            conn.execute("DROP TABLE race_events_old;")

        conn.execute("DROP TABLE races_old;")

    # Re-enable foreign keys
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;")

    # Recreate Triggers matching the new schema
    conn.executescript("""
        DROP TRIGGER IF EXISTS log_races_insert;
        CREATE TRIGGER log_races_insert
        AFTER INSERT ON races
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            SELECT
                'races',
                'INSERT',
                new.id,
                json_object(
                    'new_values', json_object(
                        'name', new.name,
                        'city', l.city,
                        'state_province', l.state_province,
                        'country', l.country,
                        'region', l.region,
                        'official_url', (SELECT url FROM official_urls WHERE id = new.official_url_id),
                        'registration_url', (SELECT url FROM official_urls WHERE id = new.registration_url_id)
                    )
                )
            FROM locations l
            WHERE l.id = new.location_id;
        END;

        DROP TRIGGER IF EXISTS log_race_events_insert;
        CREATE TRIGGER log_race_events_insert
        AFTER INSERT ON race_events
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            SELECT
                'race_events',
                'INSERT',
                ro.race_id || ' (' || new.year || ')',
                json_object(
                    'new_values', json_object(
                        'event_date', new.event_date,
                        'status', new.status,
                        'distance', ro.distance
                    )
                )
            FROM race_offerings ro
            WHERE ro.id = new.race_offering_id;
        END;

        DROP TRIGGER IF EXISTS log_race_events_update;
        CREATE TRIGGER log_race_events_update
        AFTER UPDATE ON race_events
        WHEN (
            old.event_date IS NOT new.event_date OR
            old.status IS NOT new.status
        )
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            SELECT
                'race_events',
                'UPDATE',
                ro.race_id || ' (' || new.year || ')',
                json_object(
                    'old_values', json_object(
                        'event_date', old.event_date,
                        'status', old.status
                    ),
                    'new_values', json_object(
                        'event_date', new.event_date,
                        'status', new.status
                    )
                )
            FROM race_offerings ro
            WHERE ro.id = new.race_offering_id;
        END;

        DROP TRIGGER IF EXISTS log_registration_windows_insert;
        CREATE TRIGGER log_registration_windows_insert
        AFTER INSERT ON registration_windows
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            SELECT
                'registration_windows',
                'INSERT',
                ro.race_id || ' (' || e.year || ')',
                json_object(
                    'new_values', json_object(
                        'window_type', new.window_type,
                        'description', new.description,
                        'open_date', new.open_date,
                        'close_date', new.close_date,
                        'official_url', (SELECT url FROM official_urls WHERE id = new.official_url_id)
                    )
                )
            FROM race_events e
            JOIN race_offerings ro ON e.race_offering_id = ro.id
            WHERE e.id = new.event_id;
        END;

        DROP TRIGGER IF EXISTS log_registration_windows_delete;
        CREATE TRIGGER log_registration_windows_delete
        AFTER DELETE ON registration_windows
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            SELECT
                'registration_windows',
                'DELETE',
                ro.race_id || ' (' || e.year || ')',
                json_object(
                    'old_values', json_object(
                        'window_type', old.window_type,
                        'description', old.description,
                        'open_date', old.open_date,
                        'close_date', old.close_date,
                        'official_url', (SELECT url FROM official_urls WHERE id = old.official_url_id)
                    )
                )
            FROM race_events e
            JOIN race_offerings ro ON e.race_offering_id = ro.id
            WHERE e.id = old.event_id;
        END;
    """)

    conn.commit()
