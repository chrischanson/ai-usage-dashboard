use std::collections::HashSet;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use chrono::Utc;
use rusqlite::Connection;
use tokio::time::sleep;
use ebay_watcher_core::db;
use ebay_watcher_core::ebay::EbayClient;
use ebay_watcher_core::models::BidStatus;
use ebay_watcher_core::Result;

pub struct SnipeScheduler<C: EbayClient> {
    client: C,
    lead_time_seconds: u64,
    db_path: String,
    active_bids: Arc<Mutex<HashSet<i32>>>,
}

impl<C: EbayClient + Clone + 'static> SnipeScheduler<C> {
    pub fn new(client: C, lead_time_seconds: u64, db_path: String) -> Self {
        Self {
            client,
            lead_time_seconds,
            db_path,
            active_bids: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    pub fn recover_and_cleanup(&self, conn: &Connection) -> Result<()> {
        let now = Utc::now().timestamp();
        let intents = db::get_bid_intents(conn)?;
        for intent in intents {
            let id = intent.id.expect("Bid intent must have ID");
            if intent.status == BidStatus::Pending && intent.target_time < now {
                println!("Recovering missed bid: intent_id={}, item_id={}", id, intent.item_id);
                db::update_bid_intent_status(conn, id, BidStatus::Missed, Some("Auction ended while offline"))?;
            } else if intent.status == BidStatus::Attempted {
                println!("Recovering crashed bid: intent_id={}, item_id={}", id, intent.item_id);
                db::update_bid_intent_status(conn, id, BidStatus::Failed, Some("Daemon crashed during execution"))?;
            }
        }
        Ok(())
    }

    pub fn schedule_upcoming_bids(&self, conn: &Connection) -> Result<()> {
        let now = Utc::now().timestamp();
        let pending_intents = db::get_pending_bid_intents(conn)?;
        
        let mut active = self.active_bids.lock().unwrap();
        
        for intent in pending_intents {
            let id = intent.id.expect("Pending intent must have ID");
            if active.contains(&id) {
                continue;
            }

            // Calculate execution time using shared helper
            let execution_time = ebay_watcher_core::models::calculate_snipe_execution_time(intent.target_time, self.lead_time_seconds);
            let delay = execution_time - now;

            active.insert(id);

            let client = self.client.clone();
            let db_path = self.db_path.clone();
            let active_bids = Arc::clone(&self.active_bids);

            tokio::spawn(async move {
                if delay > 0 {
                    sleep(Duration::from_secs(delay as u64)).await;
                }

                // Open DB connection for thread using shared helper
                let conn = match db::open_conn(&db_path) {
                    Ok(c) => c,
                    Err(e) => {
                        println!("Scheduler thread failed to open DB: {:?}", e);
                        active_bids.lock().unwrap().remove(&id);
                        return;
                    }
                };

                let current_intent = match db::get_bid_intents(&conn) {
                    Ok(intents) => intents.into_iter().find(|i| i.id == Some(id)),
                    Err(_) => None,
                };

                if let Some(intent) = current_intent {
                    if intent.status == BidStatus::Pending {
                        println!("Starting snipe for item={}", intent.item_id);
                        let _ = db::update_bid_intent_status(&conn, id, BidStatus::Attempted, None);
 
                        // Get token
                        let token = match db::get_token(&conn) {
                            Ok(Some(t)) => t,
                            _ => {
                                let _ = db::update_bid_intent_status(&conn, id, BidStatus::Failed, Some("No access token"));
                                active_bids.lock().unwrap().remove(&id);
                                return;
                            }
                        };

                        // Place bid
                        match client.place_bid(&token.access_token, &intent.item_id, intent.max_bid).await {
                            Ok(res) => {
                                if res.success {
                                    println!("Snipe succeeded for item={}", intent.item_id);
                                    let _ = db::update_bid_intent_status(&conn, id, BidStatus::Succeeded, None);
                                } else {
                                    let err = res.error_message.unwrap_or_else(|| "Unknown error".to_string());
                                    println!("Snipe failed for item={}: {}", intent.item_id, err);
                                    let _ = db::update_bid_intent_status(&conn, id, BidStatus::Failed, Some(&err));
                                }
                            }
                            Err(e) => {
                                let err = format!("{:?}", e);
                                println!("Snipe failed for item={}: {}", intent.item_id, err);
                                let _ = db::update_bid_intent_status(&conn, id, BidStatus::Failed, Some(&err));
                            }
                        }
                    }
                }

                // Cleanup active set
                active_bids.lock().unwrap().remove(&id);
            });
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use ebay_watcher_core::db::init_db;
    use ebay_watcher_core::ebay::MockEbayClient;
    use ebay_watcher_core::models::{OAuthToken, BidIntent};

    #[tokio::test]
    async fn test_scheduler_recovery_and_snipe() {
        let db_file = "test_scheduler.db";
        // Clean up old DB file
        let _ = fs::remove_file(db_file);

        let conn = init_db(db_file).unwrap();
        let mock_client = MockEbayClient::new();

        // 1. Setup DB token
        let token = OAuthToken {
            access_token: "tok".to_string(),
            refresh_token: "ref".to_string(),
            expires_at: Utc::now().timestamp() + 1000,
        };
        db::set_token(&conn, &token).unwrap();

        // 2. Setup bid intents
        let now = Utc::now().timestamp();
        
        // Expired intent (should be marked missed)
        let expired_intent = BidIntent {
            id: Some(1),
            item_id: "expired_item".to_string(),
            max_bid: 10.0,
            target_time: now - 10,
            status: BidStatus::Pending,
            error_message: None,
        };
        db::save_bid_intent(&conn, &expired_intent).unwrap();

        // Active/crashed intent (should be marked failed)
        let crashed_intent = BidIntent {
            id: Some(2),
            item_id: "crashed_item".to_string(),
            max_bid: 20.0,
            target_time: now - 5,
            status: BidStatus::Attempted,
            error_message: None,
        };
        db::save_bid_intent(&conn, &crashed_intent).unwrap();

        // Future intent (should be scheduled)
        let future_intent = BidIntent {
            id: Some(3),
            item_id: "future_item".to_string(),
            max_bid: 30.0,
            target_time: now + 2, // 2 seconds in future
            status: BidStatus::Pending,
            error_message: None,
        };
        db::save_bid_intent(&conn, &future_intent).unwrap();

        let scheduler = SnipeScheduler::new(mock_client, 1, db_file.to_string());
        
        // Run recovery
        scheduler.recover_and_cleanup(&conn).unwrap();

        // Verify recovery statuses
        let intents = db::get_bid_intents(&conn).unwrap();
        let i1 = intents.iter().find(|i| i.id == Some(1)).unwrap();
        let i2 = intents.iter().find(|i| i.id == Some(2)).unwrap();
        let i3 = intents.iter().find(|i| i.id == Some(3)).unwrap();
        assert_eq!(i1.status, BidStatus::Missed);
        assert_eq!(i2.status, BidStatus::Failed);
        assert_eq!(i3.status, BidStatus::Pending);

        // Run scheduler
        scheduler.schedule_upcoming_bids(&conn).unwrap();

        // Wait for snipe to trigger (2 seconds target - 1 second lead time = 1 second sleep)
        sleep(Duration::from_millis(1500)).await;

        // Verify future intent succeeded
        let conn2 = init_db(db_file).unwrap();
        let intents_after = db::get_bid_intents(&conn2).unwrap();
        let i3_after = intents_after.iter().find(|i| i.id == Some(3)).unwrap();
        assert_eq!(i3_after.status, BidStatus::Succeeded);

        let _ = fs::remove_file(db_file);
    }
}
