CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    current_price REAL NOT NULL,
    shipping_cost REAL NOT NULL,
    buy_it_now_price REAL,
    end_time INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    discovered_at INTEGER NOT NULL,
    FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bid_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    max_bid REAL NOT NULL,
    target_time INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'attempted', 'succeeded', 'failed', 'missed', 'cancelled')),
    error_message TEXT
);
