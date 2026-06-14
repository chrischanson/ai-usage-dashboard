use serde::{Serialize, Deserialize};
use std::str::FromStr;

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

/// All valid states for a bid intent, matching the SQL CHECK constraint.
/// Using a typed enum prevents invalid states from being silently stored.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum BidStatus {
    Pending,
    Attempted,
    Succeeded,
    Failed,
    Missed,
    Cancelled,
}

impl BidStatus {
    /// Returns the lowercase database string for this status.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending   => "pending",
            Self::Attempted => "attempted",
            Self::Succeeded => "succeeded",
            Self::Failed    => "failed",
            Self::Missed    => "missed",
            Self::Cancelled => "cancelled",
        }
    }
}

impl std::fmt::Display for BidStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for BidStatus {
    type Err = String;
    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        match s {
            "pending"   => Ok(Self::Pending),
            "attempted" => Ok(Self::Attempted),
            "succeeded" => Ok(Self::Succeeded),
            "failed"    => Ok(Self::Failed),
            "missed"    => Ok(Self::Missed),
            "cancelled" => Ok(Self::Cancelled),
            _           => Err(format!("Unknown bid status: {s}")),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BidIntent {
    pub id: Option<i32>,
    pub item_id: String,
    pub max_bid: f64,
    pub target_time: i64,
    pub status: BidStatus,
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

pub fn calculate_snipe_execution_time(auction_end_time: i64, lead_time_seconds: u64) -> i64 {
    auction_end_time - lead_time_seconds as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calculate_snipe_execution_time() {
        let end_time = 100000;
        let lead_time = 5;
        let execution_time = calculate_snipe_execution_time(end_time, lead_time);
        assert_eq!(execution_time, 99995);
    }
}
