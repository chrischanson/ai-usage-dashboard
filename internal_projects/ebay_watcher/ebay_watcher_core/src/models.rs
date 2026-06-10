use serde::{Serialize, Deserialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OAuthToken {
    pub access_token: String,
    pub refresh_token: String,
    pub expires_at: i64, // Unix timestamp
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Item {
    pub id: String,
    pub title: String,
    pub current_price: f64,
    pub shipping_cost: f64,
    pub buy_it_now_price: Option<f64>,
    pub end_time: i64, // Unix timestamp
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Alert {
    pub id: i32,
    pub item_id: String,
    pub is_read: bool,
    pub discovered_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BidIntent {
    pub id: Option<i32>,
    pub item_id: String,
    pub max_bid: f64,
    pub target_time: i64,
    pub status: String, // 'pending', 'attempted', 'succeeded', 'failed', 'missed', 'cancelled'
    pub error_message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SavedSearch {
    pub name: String,
    pub query: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ItemSummary {
    pub id: String,
    pub title: String,
    pub price: f64,
    pub shipping: f64,
    pub buy_it_now: Option<f64>,
    pub end_time: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BidResult {
    pub success: bool,
    pub transaction_id: Option<String>,
    pub error_message: Option<String>,
}
