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
    """Initializes the database schema and performs migrations."""
    cursor = conn.cursor()
    
    # Drop all triggers temporarily to avoid validation errors during migrations
    conn.executescript("""
        DROP TRIGGER IF EXISTS log_races_insert;
        DROP TRIGGER IF EXISTS log_race_events_insert;
        DROP TRIGGER IF EXISTS log_race_events_update;
        DROP TRIGGER IF EXISTS log_registration_windows_insert;
        DROP TRIGGER IF EXISTS log_registration_windows_delete;
    """)
    
    # 1. Create lookup/base tables that might not exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS loc_regions (
            name TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS loc_countries (
            name TEXT PRIMARY KEY,
            region_name TEXT NOT NULL,
            FOREIGN KEY(region_name) REFERENCES loc_regions(name)
        );

        CREATE TABLE IF NOT EXISTS loc_subdivisions (
            code TEXT NOT NULL,
            country_name TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY(country_name, code),
            FOREIGN KEY(country_name) REFERENCES loc_countries(name)
        );

        CREATE TABLE IF NOT EXISTS race_registration_types (
            type TEXT PRIMARY KEY,
            default_description TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS race_official_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS race_event_statuses (
            status TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS loc_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            state_province TEXT,
            country_name TEXT NOT NULL,
            FOREIGN KEY(country_name) REFERENCES loc_countries(name),
            FOREIGN KEY(country_name, state_province) REFERENCES loc_subdivisions(country_name, code),
            UNIQUE(city, state_province, country_name)
        );
    """)

    # Check race_registration_types table migration
    cursor.execute("PRAGMA table_info(race_registration_types);")
    reg_cols = [row["name"] for row in cursor.fetchall()]
    if reg_cols and "default_description" not in reg_cols:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("DROP TABLE IF EXISTS race_registration_types;")
        conn.execute("""
            CREATE TABLE race_registration_types (
                type TEXT PRIMARY KEY,
                default_description TEXT NOT NULL
            );
        """)
        conn.execute("PRAGMA foreign_keys = ON;")

    conn.execute("INSERT OR IGNORE INTO race_event_statuses (status) VALUES ('active'), ('stale'), ('carried-over');")
    conn.execute("INSERT OR IGNORE INTO race_registration_types (type, default_description) VALUES "
                 "('standard', 'Standard Registration'), "
                 "('lottery', 'Registration for the lottery'), "
                 "('qualification', 'Qualifier registration'), "
                 "('charity', 'Charity Registration'), "
                 "('invitation', 'Invitation Entry'), "
                 "('guaranteed-entry', 'Guaranteed Entry');")

    _seed_loc_regions_and_countries(conn)
    _seed_loc_subdivisions(conn)

    # Repair race_offerings if it has a stale foreign key reference to races_old
    cursor.execute("SELECT sql FROM sqlite_master WHERE name='race_offerings';")
    row_sql = cursor.fetchone()
    if row_sql and "races_old" in row_sql["sql"]:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("ALTER TABLE race_offerings RENAME TO race_offerings_old;")
        conn.execute("""
            CREATE TABLE race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES races(id),
                UNIQUE(race_id, distance)
            );
        """)
        conn.execute("INSERT INTO race_offerings (id, race_id, distance) SELECT id, race_id, distance FROM race_offerings_old;")
        conn.execute("DROP TABLE race_offerings_old;")
        conn.execute("PRAGMA foreign_keys = ON;")

    # 2. Check Locations table migration to new loc_ prefix-grouped tables
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='locations';")
    if cursor.fetchone():
        conn.commit()
        old_isolation = conn.isolation_level
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("PRAGMA legacy_alter_table = ON;")
        
        # Create new tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loc_regions (
                name TEXT PRIMARY KEY
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loc_countries (
                name TEXT PRIMARY KEY,
                region_name TEXT NOT NULL,
                FOREIGN KEY(region_name) REFERENCES loc_regions(name)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loc_subdivisions (
                code TEXT NOT NULL,
                country_name TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY(country_name, code),
                FOREIGN KEY(country_name) REFERENCES loc_countries(name)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loc_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                state_province TEXT,
                country_name TEXT NOT NULL,
                FOREIGN KEY(country_name) REFERENCES loc_countries(name),
                FOREIGN KEY(country_name, state_province) REFERENCES loc_subdivisions(country_name, code),
                UNIQUE(city, state_province, country_name)
            );
        """)
        
        # Copy data
        conn.execute("INSERT OR IGNORE INTO loc_regions SELECT * FROM regions;")
        conn.execute("INSERT OR IGNORE INTO loc_countries SELECT * FROM countries;")
        conn.execute("INSERT OR IGNORE INTO loc_subdivisions SELECT * FROM subdivisions;")
        conn.execute("INSERT OR IGNORE INTO loc_locations (id, city, state_province, country_name) SELECT id, city, state_province, country_name FROM locations;")
        
        # Rebuild races table to reference loc_locations
        conn.execute("DROP TABLE IF EXISTS races_temp;")
        conn.execute("ALTER TABLE races RENAME TO races_temp;")
        conn.execute("""
            CREATE TABLE races (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                official_url_id INTEGER NOT NULL,
                FOREIGN KEY(location_id) REFERENCES loc_locations(id),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id)
            );
        """)
        conn.execute("INSERT INTO races (id, name, location_id, official_url_id) SELECT id, name, location_id, official_url_id FROM races_temp;")
        conn.execute("DROP TABLE races_temp;")
        
        # Rebuild race_offerings to preserve foreign key to races
        conn.execute("DROP TABLE IF EXISTS race_offerings_temp;")
        conn.execute("ALTER TABLE race_offerings RENAME TO race_offerings_temp;")
        conn.execute("""
            CREATE TABLE race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES races(id),
                UNIQUE(race_id, distance)
            );
        """)
        conn.execute("INSERT INTO race_offerings (id, race_id, distance) SELECT id, race_id, distance FROM race_offerings_temp;")
        conn.execute("DROP TABLE race_offerings_temp;")
        
        # Drop old tables
        conn.execute("DROP TABLE IF EXISTS locations;")
        conn.execute("DROP TABLE IF EXISTS subdivisions;")
        conn.execute("DROP TABLE IF EXISTS countries;")
        conn.execute("DROP TABLE IF EXISTS regions;")
        
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.isolation_level = old_isolation

    # 2c. Migrate legacy tables to race_ prefix-grouped tables
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='races';")
    if cursor.fetchone():
        conn.commit()
        old_isolation = conn.isolation_level
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("PRAGMA legacy_alter_table = ON;")
        
        # Drop triggers
        conn.executescript("""
            DROP TRIGGER IF EXISTS log_races_insert;
            DROP TRIGGER IF EXISTS log_race_events_insert;
            DROP TRIGGER IF EXISTS log_race_events_update;
            DROP TRIGGER IF EXISTS log_registration_windows_insert;
            DROP TRIGGER IF EXISTS log_registration_windows_delete;
        """)

        # Create new tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_registration_types (
                type TEXT PRIMARY KEY,
                default_description TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_event_statuses (
                status TEXT PRIMARY KEY
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_confidence_levels (
                level TEXT PRIMARY KEY
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_races (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                official_url_id INTEGER NOT NULL,
                FOREIGN KEY(location_id) REFERENCES loc_locations(id),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_registration_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                window_type TEXT NOT NULL,
                description TEXT,
                open_date TEXT,
                close_date TEXT,
                official_url_id INTEGER,
                FOREIGN KEY(event_id) REFERENCES race_events(id),
                FOREIGN KEY(window_type) REFERENCES race_registration_types(type),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
                UNIQUE(event_id, window_type, open_date, close_date)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_extraction_metadata (
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
                FOREIGN KEY(confidence) REFERENCES race_confidence_levels(level)
            );
        """)

        # Copy data
        conn.execute("INSERT OR IGNORE INTO race_registration_types SELECT * FROM registration_types;")
        conn.execute("INSERT OR IGNORE INTO race_event_statuses SELECT * FROM event_statuses;")
        conn.execute("INSERT OR IGNORE INTO race_confidence_levels SELECT * FROM confidence_levels;")
        conn.execute("INSERT OR IGNORE INTO race_races SELECT * FROM races;")
        
        # Rebuild race_offerings to reference race_races
        conn.execute("DROP TABLE IF EXISTS race_offerings_temp;")
        conn.execute("ALTER TABLE race_offerings RENAME TO race_offerings_temp;")
        conn.execute("""
            CREATE TABLE race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES race_races(id),
                UNIQUE(race_id, distance)
            );
        """)
        conn.execute("INSERT INTO race_offerings (id, race_id, distance) SELECT id, race_id, distance FROM race_offerings_temp;")
        conn.execute("DROP TABLE race_offerings_temp;")

        # Rebuild race_events to reference race_event_statuses
        conn.execute("DROP TABLE IF EXISTS race_events_temp;")
        conn.execute("ALTER TABLE race_events RENAME TO race_events_temp;")
        conn.execute("""
            CREATE TABLE race_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_offering_id INTEGER NOT NULL,
                event_date TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                official_url_id INTEGER,
                FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
                FOREIGN KEY(status) REFERENCES race_event_statuses(status),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
                UNIQUE(race_offering_id, event_date)
            );
        """)
        conn.execute("INSERT INTO race_events (id, race_offering_id, event_date, status) SELECT id, race_offering_id, event_date, status FROM race_events_temp;")
        conn.execute("DROP TABLE race_events_temp;")

        # Copy child data
        conn.execute("INSERT OR IGNORE INTO race_registration_windows SELECT * FROM registration_windows;")
        conn.execute("INSERT OR IGNORE INTO race_extraction_metadata SELECT * FROM extraction_metadata;")

        # Drop old tables
        conn.execute("DROP TABLE IF EXISTS races;")
        conn.execute("DROP TABLE IF EXISTS registration_types;")
        conn.execute("DROP TABLE IF EXISTS registration_windows;")
        conn.execute("DROP TABLE IF EXISTS extraction_metadata;")
        conn.execute("DROP TABLE IF EXISTS event_statuses;")
        conn.execute("DROP TABLE IF EXISTS confidence_levels;")

        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.isolation_level = old_isolation
        conn.commit()

    # Wrap legacy Step 3/4 migrations in a check for legacy table existence
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='races';")
    if cursor.fetchone():
        # 3. Check Races table migration (removing registration_url_id, keeping only official_url_id)
        cursor.execute("PRAGMA table_info(races);")
        race_cols = [row["name"] for row in cursor.fetchall()]
        
        # If registration_url_id exists, it means we are migrating from the intermediate v1.5 schema
        # If registration_url (text) exists, it means we are migrating from the old schema
        if "registration_url_id" in race_cols or "registration_url" in race_cols:
            conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF;")
        
        # Save all unique URLs to race_official_urls first
        if "official_url" in race_cols:
            conn.execute("INSERT OR IGNORE INTO race_official_urls (url) SELECT DISTINCT official_url FROM races WHERE official_url IS NOT NULL AND official_url != '';")
        if "registration_url" in race_cols:
            conn.execute("INSERT OR IGNORE INTO race_official_urls (url) SELECT DISTINCT registration_url FROM races WHERE registration_url IS NOT NULL AND registration_url != '';")
            
        # Create race_offerings if they don't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES races(id),
                UNIQUE(race_id, distance)
            );
        """)
        
        # If transitioning from intermediate schema
        if "registration_url_id" in race_cols:
            # Map standard registration windows using old registration_url_ids for existing events
            cursor.execute("""
                SELECT e.id as event_id, r.registration_url_id
                FROM races r
                JOIN race_offerings ro ON r.id = ro.race_id
                JOIN race_events e ON ro.id = e.race_offering_id
                WHERE r.registration_url_id IS NOT NULL;
            """)
            reg_urls_to_migrate = cursor.fetchall()
            for row in reg_urls_to_migrate:
                conn.execute("""
                    INSERT OR IGNORE INTO registration_windows (event_id, window_type, open_date, close_date, official_url_id)
                    VALUES (?, 'standard', NULL, NULL, ?)
                """, (row["event_id"], row["registration_url_id"]))
        else:
            # Transitioning from old schema (with raw text columns)
            # Create race_offerings from raw races
            conn.execute("INSERT OR IGNORE INTO race_offerings (race_id, distance) SELECT id, COALESCE(distance, 'marathon') FROM races;")
            
        cursor.execute("ALTER TABLE races RENAME TO races_old;")
        conn.execute("""
            CREATE TABLE races (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                official_url_id INTEGER NOT NULL,
                FOREIGN KEY(location_id) REFERENCES locations(id),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id)
            );
        """)
        
        if "official_url_id" in race_cols:
            conn.execute("""
                INSERT INTO races (id, name, location_id, official_url_id)
                SELECT id, name, location_id, official_url_id FROM races_old;
            """)
        else:
            conn.execute("""
                INSERT INTO races (id, name, location_id, official_url_id)
                SELECT 
                    r.id, 
                    r.name, 
                    r.location_id,
                    (SELECT id FROM race_official_urls WHERE url = r.official_url)
                FROM races_old r;
            """)
            
        conn.execute("DROP TABLE races_old;")
        
        # Recreate race_offerings to point to the new races table (instead of races_old)
        cursor.execute("PRAGMA table_info(race_offerings);")
        if len(cursor.fetchall()) > 0:
            conn.execute("ALTER TABLE race_offerings RENAME TO race_offerings_old;")
            conn.execute("""
                CREATE TABLE race_offerings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id TEXT NOT NULL,
                    distance TEXT NOT NULL,
                    FOREIGN KEY(race_id) REFERENCES races(id),
                    UNIQUE(race_id, distance)
                );
            """)
            conn.execute("INSERT INTO race_offerings (id, race_id, distance) SELECT id, race_id, distance FROM race_offerings_old;")
            conn.execute("DROP TABLE race_offerings_old;")
            
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON;")

    # 4. Check Race Events table migration (removing year column, keeping event_date)
    cursor.execute("PRAGMA table_info(race_events);")
    ev_cols = [row["name"] for row in cursor.fetchall()]
    if "year" in ev_cols or "race_id" in ev_cols:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF;")
        
        # Ensure offerings table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES races(id),
                UNIQUE(race_id, distance)
            );
        """)
        
        cursor.execute("ALTER TABLE race_events RENAME TO race_events_old;")
        
        # Drop temp tables if they exist
        conn.execute("DROP TABLE IF EXISTS registration_windows_old;")
        conn.execute("DROP TABLE IF EXISTS extraction_metadata_old;")
        
        # Rename child tables to update their constraints/keys
        conn.execute("ALTER TABLE registration_windows RENAME TO registration_windows_old;")
        conn.execute("ALTER TABLE extraction_metadata RENAME TO extraction_metadata_old;")
        
        conn.execute("""
            CREATE TABLE race_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_offering_id INTEGER NOT NULL,
                event_date TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                official_url_id INTEGER,
                FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
                FOREIGN KEY(status) REFERENCES event_statuses(status),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
                UNIQUE(race_offering_id, event_date)
            );
        """)
        
        if "race_offering_id" in ev_cols:
            conn.execute("""
                INSERT INTO race_events (id, race_offering_id, event_date, status)
                SELECT id, race_offering_id, event_date, status FROM race_events_old;
            """)
        else:
            # Map race_id -> offering_id
            conn.execute("""
                INSERT INTO race_events (race_offering_id, event_date, status)
                SELECT ro.id, e.event_date, e.status
                FROM race_events_old e
                JOIN race_offerings ro ON e.race_id = ro.race_id AND ro.distance = 'marathon';
            """)
            
        # Recreate child tables pointing to the new race_events
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
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
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
        
        # Populate child tables
        conn.execute("""
            INSERT OR IGNORE INTO registration_windows (id, event_id, window_type, description, open_date, close_date, official_url_id)
            SELECT id, event_id, window_type, description, open_date, close_date, official_url_id
            FROM registration_windows_old;
        """)
        conn.execute("""
            INSERT OR IGNORE INTO extraction_metadata (id, event_id, source_url_id, extracted_at, extraction_method, confidence, notes, raw_evidence)
            SELECT id, event_id, source_url_id, extracted_at, extraction_method, confidence, notes, raw_evidence
            FROM extraction_metadata_old;
        """)
        
        conn.execute("DROP TABLE registration_windows_old;")
        conn.execute("DROP TABLE extraction_metadata_old;")
        conn.execute("DROP TABLE race_events_old;")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON;")

    # 5. Create core/remaining tables if they don't exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS race_races (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location_id INTEGER NOT NULL,
            official_url_id INTEGER NOT NULL,
            FOREIGN KEY(location_id) REFERENCES loc_locations(id),
            FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id)
        );

        CREATE TABLE IF NOT EXISTS race_offerings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id TEXT NOT NULL,
            distance TEXT NOT NULL,
            FOREIGN KEY(race_id) REFERENCES race_races(id),
            UNIQUE(race_id, distance)
        );

        CREATE TABLE IF NOT EXISTS race_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_offering_id INTEGER NOT NULL,
            event_date TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            official_url_id INTEGER,
            FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
            FOREIGN KEY(status) REFERENCES race_event_statuses(status),
            FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
            UNIQUE(race_offering_id, event_date)
        );

        CREATE TABLE IF NOT EXISTS race_registration_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            window_type TEXT NOT NULL,
            description TEXT,
            open_date TEXT,
            close_date TEXT,
            official_url_id INTEGER,
            FOREIGN KEY(event_id) REFERENCES race_events(id),
            FOREIGN KEY(window_type) REFERENCES race_registration_types(type),
            FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
            UNIQUE(event_id, window_type, open_date, close_date)
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

    # 5b. Migrate and fold race_extraction_metadata/extraction_metadata into change_log
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('race_extraction_metadata', 'extraction_metadata');")
    if cursor.fetchone():
        conn.commit()
        old_isolation = conn.isolation_level
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys = OFF;")
        
        # Find which table actually exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='race_extraction_metadata';")
        tbl_name = 'race_extraction_metadata' if cursor.fetchone() else 'extraction_metadata'
        
        # Migrate data
        conn.execute(f"""
            INSERT INTO change_log (timestamp, table_name, action, record_id, details)
            SELECT 
                COALESCE(extracted_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                'race_events',
                'EXTRACT',
                CAST(event_id AS TEXT),
                json_object(
                    'source_url', (SELECT url FROM race_official_urls WHERE id = source_url_id),
                    'extraction_method', COALESCE(extraction_method, 'seed'),
                    'confidence', COALESCE(confidence, 'unknown'),
                    'notes', COALESCE(notes, ''),
                    'raw_evidence', json(COALESCE(raw_evidence, '[]'))
                )
            FROM {tbl_name};
        """)
        
        # Drop the tables
        conn.execute("DROP TABLE IF EXISTS race_extraction_metadata;")
        conn.execute("DROP TABLE IF EXISTS extraction_metadata;")
        conn.execute("DROP TABLE IF EXISTS race_confidence_levels;")
        conn.execute("DROP TABLE IF EXISTS confidence_levels;")
        
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.isolation_level = old_isolation
        conn.commit()

    # 5c. Migrate official_urls to race_official_urls
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='official_urls';")
    if cursor.fetchone():
        conn.commit()
        old_isolation = conn.isolation_level
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("PRAGMA legacy_alter_table = ON;")
        
        # Create new table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS race_official_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL
            );
        """)
        
        # Copy data
        conn.execute("INSERT OR IGNORE INTO race_official_urls SELECT * FROM official_urls;")
        
        # Rebuild race_races to reference race_official_urls(id)
        conn.execute("DROP TABLE IF EXISTS race_races_temp;")
        conn.execute("ALTER TABLE race_races RENAME TO race_races_temp;")
        conn.execute("""
            CREATE TABLE race_races (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                official_url_id INTEGER NOT NULL,
                FOREIGN KEY(location_id) REFERENCES loc_locations(id),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id)
            );
        """)
        conn.execute("INSERT INTO race_races SELECT * FROM race_races_temp;")
        conn.execute("DROP TABLE race_races_temp;")
        
        # Rebuild race_offerings (referencing race_races)
        conn.execute("DROP TABLE IF EXISTS race_offerings_temp;")
        conn.execute("ALTER TABLE race_offerings RENAME TO race_offerings_temp;")
        conn.execute("""
            CREATE TABLE race_offerings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                distance TEXT NOT NULL,
                FOREIGN KEY(race_id) REFERENCES race_races(id),
                UNIQUE(race_id, distance)
            );
        """)
        conn.execute("INSERT INTO race_offerings SELECT * FROM race_offerings_temp;")
        conn.execute("DROP TABLE race_offerings_temp;")
        
        # Rebuild race_events (referencing race_offerings)
        conn.execute("DROP TABLE IF EXISTS race_events_temp;")
        conn.execute("ALTER TABLE race_events RENAME TO race_events_temp;")
        conn.execute("""
            CREATE TABLE race_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_offering_id INTEGER NOT NULL,
                event_date TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                official_url_id INTEGER,
                FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
                FOREIGN KEY(status) REFERENCES race_event_statuses(status),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
                UNIQUE(race_offering_id, event_date)
            );
        """)
        conn.execute("INSERT INTO race_events SELECT * FROM race_events_temp;")
        conn.execute("DROP TABLE race_events_temp;")
        
        # Rebuild race_registration_windows (referencing race_events and race_official_urls)
        conn.execute("DROP TABLE IF EXISTS race_registration_windows_temp;")
        conn.execute("ALTER TABLE race_registration_windows RENAME TO race_registration_windows_temp;")
        conn.execute("""
            CREATE TABLE race_registration_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                window_type TEXT NOT NULL,
                description TEXT,
                open_date TEXT,
                close_date TEXT,
                official_url_id INTEGER,
                FOREIGN KEY(event_id) REFERENCES race_events(id),
                FOREIGN KEY(window_type) REFERENCES race_registration_types(type),
                FOREIGN KEY(official_url_id) REFERENCES race_official_urls(id),
                UNIQUE(event_id, window_type, open_date, close_date)
            );
        """)
        conn.execute("INSERT INTO race_registration_windows SELECT * FROM race_registration_windows_temp;")
        conn.execute("DROP TABLE race_registration_windows_temp;")
        
        # Drop old table
        conn.execute("DROP TABLE IF EXISTS official_urls;")
        
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.isolation_level = old_isolation
        conn.commit()

    # 5d. Migrate race_events table to add official_url_id if missing
    cursor.execute("PRAGMA table_info(race_events);")
    event_cols = [row["name"] for row in cursor.fetchall()]
    if event_cols and "official_url_id" not in event_cols:
        conn.execute("ALTER TABLE race_events ADD COLUMN official_url_id INTEGER REFERENCES race_official_urls(id);")
        conn.execute("""
            UPDATE race_events
            SET official_url_id = (
                SELECT r.official_url_id
                FROM race_races r
                JOIN race_offerings ro ON r.id = ro.race_id
                WHERE ro.id = race_events.race_offering_id
            )
            WHERE official_url_id IS NULL;
        """)
        conn.commit()

    # 6. Recreate SQL Triggers (Paused/Disabled during system building)
    if False:
        conn.executescript("""
            DROP TRIGGER IF EXISTS log_races_insert;
            CREATE TRIGGER log_races_insert
            AFTER INSERT ON race_races
            BEGIN
                INSERT INTO change_log (table_name, action, record_id, details)
                SELECT
                    'race_races',
                    'INSERT',
                    new.id,
                    json_object(
                        'new_values', json_object(
                            'name', new.name,
                            'city', l.city,
                            'state_province', l.state_province,
                            'country', l.country_name,
                            'official_url', (SELECT url FROM race_official_urls WHERE id = new.official_url_id)
                        )
                    )
                FROM loc_locations l
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
                    ro.race_id || ' - ' || ro.distance || ' (' || coalesce(new.event_date, 'TBD') || ')',
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
                    ro.race_id || ' - ' || ro.distance || ' (' || coalesce(new.event_date, 'TBD') || ')',
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
            AFTER INSERT ON race_registration_windows
            BEGIN
                INSERT INTO change_log (table_name, action, record_id, details)
                SELECT
                    'race_registration_windows',
                    'INSERT',
                    ro.race_id || ' - ' || ro.distance || ' (' || coalesce(e.event_date, 'TBD') || ')',
                    json_object(
                        'new_values', json_object(
                            'window_type', new.window_type,
                            'description', new.description,
                            'open_date', new.open_date,
                            'close_date', new.close_date,
                            'official_url', (SELECT url FROM race_official_urls WHERE id = new.official_url_id)
                        )
                    )
                FROM race_events e
                JOIN race_offerings ro ON e.race_offering_id = ro.id
                WHERE e.id = new.event_id;
            END;

            DROP TRIGGER IF EXISTS log_registration_windows_delete;
            CREATE TRIGGER log_registration_windows_delete
            AFTER DELETE ON race_registration_windows
            BEGIN
                INSERT INTO change_log (table_name, action, record_id, details)
                SELECT
                    'race_registration_windows',
                    'DELETE',
                    ro.race_id || ' - ' || ro.distance || ' (' || coalesce(e.event_date, 'TBD') || ')',
                    json_object(
                        'old_values', json_object(
                            'window_type', old.window_type,
                            'description', old.description,
                            'open_date', old.open_date,
                            'close_date', old.close_date,
                            'official_url', (SELECT url FROM race_official_urls WHERE id = old.official_url_id)
                        )
                    )
                FROM race_events e
                JOIN race_offerings ro ON e.race_offering_id = ro.id
                WHERE e.id = old.event_id;
            END;
        """)

    conn.commit()


def _seed_loc_regions_and_countries(conn: sqlite3.Connection) -> None:
    regions = ["North America", "South America", "Europe", "Asia", "Africa", "Oceania", "Unknown"]
    for r in regions:
        conn.execute("INSERT OR IGNORE INTO loc_regions (name) VALUES (?)", (r,))
        
    country_mapping = {
        "North America": [
            "United States", "Canada", "Mexico", "Greenland", "Bermuda",
            "Bahamas", "Costa Rica", "Cuba", "Dominican Republic", "El Salvador",
            "Guatemala", "Haiti", "Honduras", "Jamaica", "Nicaragua", "Panama",
            "Puerto Rico", "Trinidad and Tobago",
        ],
        "South America": [
            "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Venezuela",
            "Bolivia", "Ecuador", "Paraguay", "Uruguay", "Guide", "Suriname",
        ],
        "Europe": [
            "United Kingdom", "Germany", "France", "Italy", "Spain", "Netherlands",
            "Switzerland", "Sweden", "Norway", "Denmark", "Finland", "Belgium",
            "Austria", "Ireland", "Portugal", "Greece", "Poland", "Czechia",
            "Romania", "Hungary", "Russia", "Turkey", "Ukraine", "Croatia",
            "Serbia", "Slovenia", "Slovakia", "Bulgaria", "Estonia", "Latvia",
            "Lithuania", "Iceland", "Luxembourg", "Monaco", "Cyprus", "England",
            "Northern Ireland", "Scotland", "Wales",
        ],
        "Asia": [
            "Japan", "China", "South Korea", "India", "Thailand", "Singapore",
            "Taiwan", "Indonesia", "Philippines", "Malaysia", "Vietnam",
            "United Arab Emirates", "Qatar", "Saudi Arabia", "Israel", "Kazakhstan",
            "Uzbekistan", "Kyrgyzstan", "Bahrain", "Kuwait", "Oman",
            "Hong Kong", "Sri Lanka", "Nepal",
        ],
        "Africa": [
            "South Africa", "Kenya", "Ethiopia", "Nigeria", "Morocco", "Tunisia",
            "Rwanda", "Uganda", "Tanzania", "Ghana", "Algeria", "Egypt",
            "Zimbabwe", "Zambia", "Namibia", "Botswana", "Ivory Coast",
            "Senegal", "Mozambique", "Djibouti", "Lesotho",
        ],
        "Oceania": [
            "Australia", "New Zealand", "Fiji", "Papua New Guinea", "Samoa",
        ]
    }
    
    for r_name, countries in country_mapping.items():
        for c_name in countries:
            conn.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES (?, ?)", (c_name, r_name))


def _seed_loc_subdivisions(conn: sqlite3.Connection) -> None:
    json_path = Path(__file__).parent / "iso_3166_2.json"
    if not json_path.exists():
        return
        
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
    except Exception:
        return

    COUNTRY_NAME_MAP = {
        "Czech Republic": "Czechia",
        "Korea (South)": "South Korea",
    }

    cursor = conn.cursor()
    records = []

    for c_code, c_val in json_data.items():
        c_name = COUNTRY_NAME_MAP.get(c_val["name"], c_val["name"])
        
        # Ensure country exists in countries
        cursor.execute("SELECT 1 FROM loc_countries WHERE name = ?", (c_name,))
        if not cursor.fetchone():
            cursor.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES (?, 'Unknown')", (c_name,))

        for div_code, div_name in c_val.get("divisions", {}).items():
            short_code = div_code.split("-")[-1]
            records.append((short_code, c_name, div_name))

            # Handle UK nations
            if c_name == "United Kingdom" and div_name in ["England", "Northern Ireland", "Scotland", "Wales"]:
                cursor.execute("SELECT 1 FROM loc_countries WHERE name = ?", (div_name,))
                if not cursor.fetchone():
                    cursor.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES (?, 'Europe')", (div_name,))
                records.append((short_code, div_name, div_name))

    # Add manual additions
    records.append(("CMX", "Mexico", "Ciudad de México"))

    cursor.executemany(
        "INSERT OR IGNORE INTO loc_subdivisions (code, country_name, name) VALUES (?, ?, ?)",
        records
    )
