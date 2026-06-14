use chrono::Utc;
use ebay_watcher_core::ebay::EbayClient;
use ebay_watcher_core::db;
use ebay_watcher_core::models::Item;
use ebay_watcher_core::Result;

async fn with_backoff<F, Fut, T>(f: F) -> Result<T>
where
    F: Fn() -> Fut,
    Fut: std::future::Future<Output = Result<T>>,
{
    let mut delay = std::time::Duration::from_secs(1);
    let max_delay = std::time::Duration::from_secs(16);
    let max_retries = 3;
    for attempt in 0..=max_retries {
        match f().await {
            Ok(val) => return Ok(val),
            Err(e) => {
                if !e.is_transient() || attempt == max_retries {
                    return Err(e);
                }
                println!("API call failed (transient): {:?}. Retrying in {:?} (attempt {}/{})", e, delay, attempt + 1, max_retries);
                tokio::time::sleep(delay).await;
                delay = std::cmp::min(delay * 2, max_delay);
            }
        }
    }
    unreachable!()
}

pub struct SyncEngine<C: EbayClient> {
    client: C,
}

impl<C: EbayClient> SyncEngine<C> {
    pub fn new(client: C) -> Self {
        Self { client }
    }

    pub async fn run_sync_cycle(&self, db_path: &str) -> Result<()> {
        let token = {
            let conn = db::open_conn(db_path)?;
            match db::get_token(&conn)? {
                Some(t) => t,
                None => {
                    println!("No OAuth token found in database. Please log in first.");
                    return Ok(());
                }
            }
        };

        // Proactive token refresh
        let token = if Utc::now().timestamp() + 300 >= token.expires_at {
            println!("Access token expiring soon. Refreshing...");
            match with_backoff(|| self.client.refresh_token(&token.refresh_token)).await {
                Ok(new_token) => {
                    let conn = db::open_conn(db_path)?;
                    db::set_token(&conn, &new_token)?;
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
        let (watched_items, saved_searches) = match with_backoff(|| self.client.fetch_my_ebay_buying(&token.access_token)).await {
            Ok(data) => data,
            Err(e) => {
                println!("Failed to fetch buying data from eBay: {:?}", e);
                return Err(e);
            }
        };

        // Save watched items
        {
            let conn = db::open_conn(db_path)?;
            for item in watched_items {
                db::save_item(&conn, &item)?;
            }
        }

        // Run saved searches
        for search in saved_searches {
            println!("Polling saved search: {}", search.name);
            match with_backoff(|| self.client.search_items(&token.access_token, &search.query)).await {
                Ok(summaries) => {
                    let conn = db::open_conn(db_path)?;
                    for summary in summaries {
                        let existing = db::get_item(&conn, &summary.id)?;
                        if existing.is_none() {
                            let item = Item {
                                id: summary.id.clone(),
                                title: summary.title.clone(),
                                current_price: summary.price,
                                shipping_cost: summary.shipping,
                                buy_it_now_price: summary.buy_it_now,
                                end_time: summary.end_time,
                            };
                            db::save_item(&conn, &item)?;
                            db::add_alert(&conn, &summary.id, Utc::now().timestamp())?;
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

    #[tokio::test]
    async fn test_sync_cycle_discovers_new_item() {
        let db_file = "test_sync.db";
        let _ = std::fs::remove_file(db_file);
        let conn = init_db(db_file).unwrap();
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

        std::mem::drop(conn);

        let engine = SyncEngine::new(mock_client);
        engine.run_sync_cycle(db_file).await.unwrap();

        let conn = db::open_conn(db_file).unwrap();

        // Verify that the new item was saved
        let item = db::get_item(&conn, "new_item_123").unwrap().unwrap();
        assert_eq!(item.title, "Rare Vintage Item");

        // Verify that an alert was created
        let alerts = db::get_unread_alerts(&conn).unwrap();
        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].item_id, "new_item_123");

        std::mem::drop(conn);
        let _ = std::fs::remove_file(db_file);
    }
}
