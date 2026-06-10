use rusqlite::Connection;
use chrono::Utc;
use ebay_watcher_core::ebay::EbayClient;
use ebay_watcher_core::db;
use ebay_watcher_core::models::Item;
use ebay_watcher_core::Result;

pub struct SyncEngine<C: EbayClient> {
    client: C,
}

impl<C: EbayClient> SyncEngine<C> {
    pub fn new(client: C) -> Self {
        Self { client }
    }

    pub fn run_sync_cycle(&self, conn: &Connection) -> Result<()> {
        let token = match db::get_token(conn)? {
            Some(t) => t,
            None => {
                println!("No OAuth token found in database. Please log in first.");
                return Ok(());
            }
        };

        // Proactive token refresh
        let token = if Utc::now().timestamp() + 300 >= token.expires_at {
            println!("Access token expiring soon. Refreshing...");
            match self.client.refresh_token(&token.refresh_token) {
                Ok(new_token) => {
                    db::set_token(conn, &new_token)?;
                    new_token
                }
                Err(e) => {
                    println!("Failed to refresh OAuth token: {:?}", e);
                    return Err(e);
                }
            }
        } else {
            token
        };

        // Fetch watchlist and saved searches
        let (watched_items, saved_searches) = match self.client.fetch_my_ebay_buying(&token.access_token) {
            Ok(data) => data,
            Err(e) => {
                println!("Failed to fetch buying data from eBay: {:?}", e);
                return Err(e);
            }
        };

        // Save watched items
        for item in watched_items {
            db::save_item(conn, &item)?;
        }

        // Run saved searches
        for search in saved_searches {
            println!("Polling saved search: {}", search.name);
            match self.client.search_items(&token.access_token, &search.query) {
                Ok(summaries) => {
                    for summary in summaries {
                        let existing = db::get_item(conn, &summary.id)?;
                        if existing.is_none() {
                            let item = Item {
                                id: summary.id.clone(),
                                title: summary.title.clone(),
                                current_price: summary.price,
                                shipping_cost: summary.shipping,
                                buy_it_now_price: summary.buy_it_now,
                                end_time: summary.end_time,
                            };
                            db::save_item(conn, &item)?;
                            db::add_alert(conn, &summary.id, Utc::now().timestamp())?;
                            println!("New item discovered: {} - {}", summary.title, summary.id);
                        }
                    }
                }
                Err(e) => {
                    println!("Failed to run search for query '{}': {:?}", search.query, e);
                }
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ebay_watcher_core::db::init_db;
    use ebay_watcher_core::ebay::MockEbayClient;
    use ebay_watcher_core::models::{OAuthToken, SavedSearch, Item};

    #[test]
    fn test_sync_cycle_discovers_new_item() {
        let conn = init_db(":memory:").unwrap();
        let mock_client = MockEbayClient::new();

        // 1. Setup DB token
        let token = OAuthToken {
            access_token: "tok".to_string(),
            refresh_token: "ref".to_string(),
            expires_at: Utc::now().timestamp() + 1000,
        };
        db::set_token(&conn, &token).unwrap();

        // 2. Setup mock client searches and items
        {
            let mut mock_searches = mock_client.saved_searches.lock().unwrap();
            mock_searches.push(SavedSearch {
                name: "test query".to_string(),
                query: "test query".to_string(),
            });

            let mut mock_items = mock_client.items.lock().unwrap();
            mock_items.push(Item {
                id: "new_item_123".to_string(),
                title: "Rare Vintage Item".to_string(),
                current_price: 50.0,
                shipping_cost: 10.0,
                buy_it_now_price: None,
                end_time: Utc::now().timestamp() + 3600,
            });
        }

        let engine = SyncEngine::new(mock_client);
        engine.run_sync_cycle(&conn).unwrap();

        // Verify that the new item was saved
        let item = db::get_item(&conn, "new_item_123").unwrap().unwrap();
        assert_eq!(item.title, "Rare Vintage Item");

        // Verify that an alert was created
        let alerts = db::get_unread_alerts(&conn).unwrap();
        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].item_id, "new_item_123");
    }
}
