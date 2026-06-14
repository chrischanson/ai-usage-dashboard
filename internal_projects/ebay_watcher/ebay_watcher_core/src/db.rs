use rusqlite::{Connection, params, OptionalExtension};
use rusqlite::types::{FromSql, FromSqlError, FromSqlResult, ToSql, ToSqlOutput, ValueRef};
use std::path::Path;
use crate::error::Result;
use crate::models::{OAuthToken, Item, Alert, BidIntent, BidStatus};

impl ToSql for BidStatus {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        Ok(ToSqlOutput::Borrowed(ValueRef::Text(self.as_str().as_bytes())))
    }
}

impl FromSql for BidStatus {
    fn column_result(value: ValueRef<'_>) -> FromSqlResult<Self> {
        value.as_str()?.parse().map_err(|_| FromSqlError::InvalidType)
    }
}

pub fn init_db<P: AsRef<Path>>(path: P) -> Result<Connection> {
    let conn = Connection::open(path)?;
    
    // Enable WAL mode
    conn.pragma_update(None, "journal_mode", "WAL")?;
    // Set synchronous mode to NORMAL
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    // Set busy timeout to 5000ms
    conn.busy_timeout(std::time::Duration::from_millis(5000))?;

    // Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;", [])?;

    // Apply migrations
    let migration_sql = include_str!("../../migrations/001_initial.sql");
    conn.execute_batch(migration_sql)?;

    Ok(conn)
}

/// Opens and configures a connection to an **already-migrated** database.
/// Unlike [`init_db`], this does **not** re-run migrations — use for
/// per-tick daemon connections where the schema is known to be up to date.
pub fn open_conn<P: AsRef<Path>>(path: P) -> Result<Connection> {
    let conn = Connection::open(path)?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.busy_timeout(std::time::Duration::from_millis(5000))?;
    conn.execute("PRAGMA foreign_keys = ON;", [])?;
    Ok(conn)
}

pub fn get_token(conn: &Connection) -> Result<Option<OAuthToken>> {
    let mut stmt = conn.prepare("SELECT access_token, refresh_token, expires_at FROM tokens WHERE id = 1")?;
    let token = stmt.query_row([], |row| {
        Ok(OAuthToken {
            access_token: row.get(0)?,
            refresh_token: row.get(1)?,
            expires_at: row.get(2)?,
        })
    }).optional()?;
    Ok(token)
}

pub fn set_token(conn: &Connection, token: &OAuthToken) -> Result<()> {
    conn.execute(
        "INSERT INTO tokens (id, access_token, refresh_token, expires_at)
         VALUES (1, ?1, ?2, ?3)
         ON CONFLICT(id) DO UPDATE SET
         access_token = excluded.access_token,
         refresh_token = excluded.refresh_token,
         expires_at = excluded.expires_at",
        params![token.access_token, token.refresh_token, token.expires_at],
    )?;
    Ok(())
}

pub fn save_item(conn: &Connection, item: &Item) -> Result<()> {
    conn.execute(
        "INSERT INTO items (id, title, current_price, shipping_cost, buy_it_now_price, end_time)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)
         ON CONFLICT(id) DO UPDATE SET
         title = excluded.title,
         current_price = excluded.current_price,
         shipping_cost = excluded.shipping_cost,
         buy_it_now_price = excluded.buy_it_now_price,
         end_time = excluded.end_time",
        params![
            item.id,
            item.title,
            item.current_price,
            item.shipping_cost,
            item.buy_it_now_price,
            item.end_time
        ],
    )?;
    Ok(())
}

pub fn get_item(conn: &Connection, id: &str) -> Result<Option<Item>> {
    let mut stmt = conn.prepare(
        "SELECT id, title, current_price, shipping_cost, buy_it_now_price, end_time 
         FROM items WHERE id = ?1"
    )?;
    let item = stmt.query_row(params![id], |row| {
        Ok(Item {
            id: row.get(0)?,
            title: row.get(1)?,
            current_price: row.get(2)?,
            shipping_cost: row.get(3)?,
            buy_it_now_price: row.get(4)?,
            end_time: row.get(5)?,
        })
    }).optional()?;
    Ok(item)
}

pub fn get_items(conn: &Connection) -> Result<Vec<Item>> {
    let mut stmt = conn.prepare(
        "SELECT id, title, current_price, shipping_cost, buy_it_now_price, end_time FROM items"
    )?;
    let item_iter = stmt.query_map([], |row| {
        Ok(Item {
            id: row.get(0)?,
            title: row.get(1)?,
            current_price: row.get(2)?,
            shipping_cost: row.get(3)?,
            buy_it_now_price: row.get(4)?,
            end_time: row.get(5)?,
        })
    })?;
    let mut items = Vec::new();
    for item in item_iter {
        items.push(item?);
    }
    Ok(items)
}

pub fn add_alert(conn: &Connection, item_id: &str, discovered_at: i64) -> Result<()> {
    conn.execute(
        "INSERT INTO alerts (item_id, is_read, discovered_at) VALUES (?1, 0, ?2)",
        params![item_id, discovered_at],
    )?;
    Ok(())
}

pub fn get_unread_alerts(conn: &Connection) -> Result<Vec<Alert>> {
    let mut stmt = conn.prepare("SELECT id, item_id, is_read, discovered_at FROM alerts WHERE is_read = 0")?;
    let alert_iter = stmt.query_map([], |row| {
        Ok(Alert {
            id: row.get(0)?,
            item_id: row.get(1)?,
            is_read: row.get::<_, i32>(2)? != 0,
            discovered_at: row.get(3)?,
        })
    })?;
    let mut alerts = Vec::new();
    for alert in alert_iter {
        alerts.push(alert?);
    }
    Ok(alerts)
}

pub fn mark_alerts_as_read(conn: &Connection, item_id: &str) -> Result<()> {
    conn.execute(
        "UPDATE alerts SET is_read = 1 WHERE item_id = ?1",
        params![item_id],
    )?;
    Ok(())
}

pub fn save_bid_intent(conn: &Connection, intent: &BidIntent) -> Result<i32> {
    if let Some(id) = intent.id {
        conn.execute(
            "INSERT INTO bid_intents (id, item_id, max_bid, target_time, status, error_message)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(id) DO UPDATE SET
             item_id = excluded.item_id,
             max_bid = excluded.max_bid,
             target_time = excluded.target_time,
             status = excluded.status,
             error_message = excluded.error_message",
            params![id, intent.item_id, intent.max_bid, intent.target_time, intent.status, intent.error_message],
        )?;
        Ok(id)
    } else {
        conn.execute(
            "INSERT INTO bid_intents (item_id, max_bid, target_time, status, error_message)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![intent.item_id, intent.max_bid, intent.target_time, intent.status, intent.error_message],
        )?;
        let row_id = conn.last_insert_rowid();
        Ok(row_id as i32)
    }
}

pub fn get_bid_intents(conn: &Connection) -> Result<Vec<BidIntent>> {
    let mut stmt = conn.prepare("SELECT id, item_id, max_bid, target_time, status, error_message FROM bid_intents")?;
    let intent_iter = stmt.query_map([], |row| {
        Ok(BidIntent {
            id: Some(row.get(0)?),
            item_id: row.get(1)?,
            max_bid: row.get(2)?,
            target_time: row.get(3)?,
            status: row.get(4)?,
            error_message: row.get(5)?,
        })
    })?;
    let mut intents = Vec::new();
    for intent in intent_iter {
        intents.push(intent?);
    }
    Ok(intents)
}

pub fn get_pending_bid_intents(conn: &Connection) -> Result<Vec<BidIntent>> {
    let mut stmt = conn.prepare(
        "SELECT id, item_id, max_bid, target_time, status, error_message 
         FROM bid_intents WHERE status = 'pending'"
    )?;
    let intent_iter = stmt.query_map([], |row| {
        Ok(BidIntent {
            id: Some(row.get(0)?),
            item_id: row.get(1)?,
            max_bid: row.get(2)?,
            target_time: row.get(3)?,
            status: row.get(4)?,
            error_message: row.get(5)?,
        })
    })?;
    let mut intents = Vec::new();
    for intent in intent_iter {
        intents.push(intent?);
    }
    Ok(intents)
}

pub fn update_bid_intent_status(
    conn: &Connection,
    id: i32,
    status: BidStatus,
    error_message: Option<&str>,
) -> Result<()> {
    conn.execute(
        "UPDATE bid_intents SET status = ?1, error_message = ?2 WHERE id = ?3",
        params![status, error_message, id],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_db_migration_and_basic_ops() {
        let conn = init_db(":memory:").unwrap();
        
        // Test oauth tokens
        let token = OAuthToken {
            access_token: "access".to_string(),
            refresh_token: "refresh".to_string(),
            expires_at: 12345,
        };
        set_token(&conn, &token).unwrap();
        let fetched_token = get_token(&conn).unwrap().unwrap();
        assert_eq!(fetched_token.access_token, "access");
        assert_eq!(fetched_token.refresh_token, "refresh");
        assert_eq!(fetched_token.expires_at, 12345);

        // Test items
        let item = Item {
            id: "item1".to_string(),
            title: "Test Item".to_string(),
            current_price: 10.0,
            shipping_cost: 2.5,
            buy_it_now_price: Some(15.0),
            end_time: 20000,
        };
        save_item(&conn, &item).unwrap();
        let fetched_item = get_item(&conn, "item1").unwrap().unwrap();
        assert_eq!(fetched_item, item);

        // Test get_items
        let items = get_items(&conn).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0], item);

        // Test alerts
        add_alert(&conn, "item1", 15000).unwrap();
        let unread = get_unread_alerts(&conn).unwrap();
        assert_eq!(unread.len(), 1);
        assert_eq!(unread[0].item_id, "item1");

        mark_alerts_as_read(&conn, "item1").unwrap();
        let unread_after = get_unread_alerts(&conn).unwrap();
        assert_eq!(unread_after.len(), 0);

        // Test bid intents
        let intent = BidIntent {
            id: None,
            item_id: "item1".to_string(),
            max_bid: 12.0,
            target_time: 19995,
            status: BidStatus::Pending,
            error_message: None,
        };
        let intent_id = save_bid_intent(&conn, &intent).unwrap();
        
        let pending = get_pending_bid_intents(&conn).unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].max_bid, 12.0);
        assert_eq!(pending[0].id, Some(intent_id));

        update_bid_intent_status(&conn, intent_id, BidStatus::Succeeded, None).unwrap();
        let pending_after = get_pending_bid_intents(&conn).unwrap();
        assert_eq!(pending_after.len(), 0);

        let all_intents = get_bid_intents(&conn).unwrap();
        assert_eq!(all_intents.len(), 1);
        assert_eq!(all_intents[0].status, BidStatus::Succeeded);
    }
}
