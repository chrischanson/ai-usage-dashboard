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
            country TEXT NOT NULL,
            region TEXT NOT NULL,
            UNIQUE(city, country)
        );

        CREATE TABLE IF NOT EXISTS event_statuses (
            status TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS confidence_levels (
            level TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS races (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location_id INTEGER NOT NULL,
            distance TEXT NOT NULL DEFAULT 'marathon',
            official_url TEXT NOT NULL,
            registration_url TEXT,
            FOREIGN KEY(location_id) REFERENCES locations(id)
        );

        CREATE TABLE IF NOT EXISTS race_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id TEXT NOT NULL,
            year INTEGER NOT NULL,
            event_date TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY(race_id) REFERENCES races(id),
            FOREIGN KEY(status) REFERENCES event_statuses(status),
            UNIQUE(race_id, year)
        );

        CREATE TABLE IF NOT EXISTS official_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL
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

        CREATE TRIGGER IF NOT EXISTS log_races_insert
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
                        'country', l.country,
                        'region', l.region,
                        'distance', new.distance,
                        'official_url', new.official_url,
                        'registration_url', new.registration_url
                    )
                )
            FROM locations l
            WHERE l.id = new.location_id;
        END;

        CREATE TRIGGER IF NOT EXISTS log_race_events_insert
        AFTER INSERT ON race_events
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            VALUES (
                'race_events',
                'INSERT',
                new.race_id || ' (' || new.year || ')',
                json_object(
                    'new_values', json_object(
                        'event_date', new.event_date,
                        'status', new.status
                    )
                )
            );
        END;

        CREATE TRIGGER IF NOT EXISTS log_race_events_update
        AFTER UPDATE ON race_events
        WHEN (
            old.event_date IS NOT new.event_date OR
            old.status IS NOT new.status
        )
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            VALUES (
                'race_events',
                'UPDATE',
                new.race_id || ' (' || new.year || ')',
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
            );
        END;

        DROP TRIGGER IF EXISTS log_registration_windows_insert;
        CREATE TRIGGER log_registration_windows_insert
        AFTER INSERT ON registration_windows
        BEGIN
            INSERT INTO change_log (table_name, action, record_id, details)
            SELECT
                'registration_windows',
                'INSERT',
                e.race_id || ' (' || e.year || ')',
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
                e.race_id || ' (' || e.year || ')',
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
            WHERE e.id = old.event_id;
        END;
    """)
    conn.execute("INSERT OR IGNORE INTO event_statuses (status) VALUES ('active'), ('stale'), ('carried-over');")
    conn.execute("INSERT OR IGNORE INTO confidence_levels (level) VALUES ('high'), ('medium'), ('low'), ('unknown');")
    conn.execute("INSERT OR IGNORE INTO registration_types (type) VALUES ('standard'), ('lottery'), ('qualification'), ('charity'), ('invitation');")
    
    # Automated schema migration: check if official_url_id column exists in registration_windows
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(registration_windows);")
    columns = [row["name"] for row in cursor.fetchall()]
    if "official_url_id" not in columns:
        conn.execute("ALTER TABLE registration_windows ADD COLUMN official_url_id INTEGER REFERENCES official_urls(id);")
        
        # Check if source_url exists in extraction_metadata before querying it
        cursor.execute("PRAGMA table_info(extraction_metadata);")
        em_cols = [row["name"] for row in cursor.fetchall()]
        if "source_url" in em_cols:
            # Populate official_urls table from unique URLs in extraction_metadata
            conn.execute("""
                INSERT OR IGNORE INTO official_urls (url)
                SELECT DISTINCT source_url FROM extraction_metadata WHERE source_url IS NOT NULL AND source_url != '';
            """)
            
            # Update existing registration_windows rows to link to official_urls
            conn.execute("""
                UPDATE registration_windows
                SET official_url_id = (
                    SELECT o.id FROM official_urls o
                    JOIN extraction_metadata m ON o.url = m.source_url
                    WHERE m.event_id = registration_windows.event_id
                    LIMIT 1
                )
                WHERE official_url_id IS NULL;
            """)
    
    # Automated schema migration: check if source_url_id column exists in extraction_metadata
    cursor.execute("PRAGMA table_info(extraction_metadata);")
    em_columns = [row["name"] for row in cursor.fetchall()]
    if "source_url_id" not in em_columns:
        if "source_url" in em_columns:
            conn.execute("ALTER TABLE extraction_metadata ADD COLUMN source_url_id INTEGER REFERENCES official_urls(id);")
            
            # Populate official_urls table from unique URLs in extraction_metadata
            conn.execute("""
                INSERT OR IGNORE INTO official_urls (url)
                SELECT DISTINCT source_url FROM extraction_metadata WHERE source_url IS NOT NULL AND source_url != '';
            """)
            
            # Update source_url_id foreign keys matching the string source_url
            conn.execute("""
                UPDATE extraction_metadata
                SET source_url_id = (
                    SELECT id FROM official_urls WHERE url = extraction_metadata.source_url
                )
                WHERE source_url IS NOT NULL AND source_url != '';
            """)
            
            # Drop the legacy source_url column
            try:
                conn.execute("ALTER TABLE extraction_metadata DROP COLUMN source_url;")
            except sqlite3.OperationalError:
                pass
        else:
            conn.execute("ALTER TABLE extraction_metadata ADD COLUMN source_url_id INTEGER REFERENCES official_urls(id);")

    # Automated schema migration: check if registration_windows has a foreign key to registration_types
    cursor.execute("PRAGMA foreign_key_list(registration_windows);")
    fks = [row["table"] for row in cursor.fetchall()]
    if "registration_types" not in fks:
        conn.execute("CREATE TABLE IF NOT EXISTS registration_types (type TEXT PRIMARY KEY);")
        conn.execute("INSERT OR IGNORE INTO registration_types (type) VALUES ('standard'), ('lottery'), ('qualification'), ('charity'), ('invitation');")
        
        conn.execute("ALTER TABLE registration_windows RENAME TO registration_windows_old;")
        
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
            INSERT OR IGNORE INTO registration_types (type)
            SELECT DISTINCT window_type FROM registration_windows_old WHERE window_type IS NOT NULL;
        """)
        
        conn.execute("""
            INSERT INTO registration_windows (id, event_id, window_type, description, open_date, close_date, official_url_id)
            SELECT id, event_id, window_type, description, open_date, close_date, official_url_id FROM registration_windows_old;
        """)
        
        conn.execute("DROP TABLE registration_windows_old;")

    conn.commit()
