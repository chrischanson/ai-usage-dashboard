use std::sync::Arc;
use chrono::Utc;
use serde_json::Value;
use crate::config::Config;
use crate::error::{Error, Result};
use crate::models::{OAuthToken, Item, SavedSearch, ItemSummary, BidResult};

pub trait EbayClient: Send + Sync {
    fn get_token(&self, code: &str) -> Result<OAuthToken>;
    fn refresh_token(&self, refresh_token: &str) -> Result<OAuthToken>;
    fn fetch_my_ebay_buying(&self, token: &str) -> Result<(Vec<Item>, Vec<SavedSearch>)>;
    fn search_items(&self, token: &str, query: &str) -> Result<Vec<ItemSummary>>;
    fn place_bid(&self, token: &str, item_id: &str, amount: f64) -> Result<BidResult>;
}

pub struct RealEbayClient {
    config: Config,
    http_client: reqwest::blocking::Client,
}

impl RealEbayClient {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            http_client: reqwest::blocking::Client::new(),
        }
    }

    fn identity_url(&self) -> &str {
        if self.config.ebay.sandbox {
            "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        } else {
            "https://api.ebay.com/identity/v1/oauth2/token"
        }
    }

    fn trading_url(&self) -> &str {
        if self.config.ebay.sandbox {
            "https://api.sandbox.ebay.com/ws/api.dll"
        } else {
            "https://api.ebay.com/ws/api.dll"
        }
    }

    fn browse_url(&self) -> &str {
        if self.config.ebay.sandbox {
            "https://api.sandbox.ebay.com/buy/browse/v1"
        } else {
            "https://api.ebay.com/buy/browse/v1"
        }
    }
}

impl EbayClient for RealEbayClient {
    fn get_token(&self, code: &str) -> Result<OAuthToken> {
        let auth = format!("{}:{}", self.config.ebay.client_id, self.config.ebay.client_secret);
        let basic_auth = format!("Basic {}", base64::Engine::encode(&base64::prelude::BASE64_STANDARD, auth));

        let res = self.http_client.post(self.identity_url())
            .header("Authorization", basic_auth)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .body(format!(
                "grant_type=authorization_code&code={}&redirect_uri={}",
                code, self.config.ebay.ru_name
            ))
            .send()?;

        if !res.status().is_success() {
            return Err(Error::OAuth(format!("Failed to get token: HTTP {}", res.status())));
        }

        let body: Value = res.json()?;
        let access_token = body["access_token"].as_str().ok_or_else(|| Error::OAuth("No access token".into()))?.to_string();
        let refresh_token = body["refresh_token"].as_str().ok_or_else(|| Error::OAuth("No refresh token".into()))?.to_string();
        let expires_in = body["expires_in"].as_i64().ok_or_else(|| Error::OAuth("No expires_in".into()))?;
        let expires_at = Utc::now().timestamp() + expires_in;

        Ok(OAuthToken { access_token, refresh_token, expires_at })
    }

    fn refresh_token(&self, refresh_token: &str) -> Result<OAuthToken> {
        let auth = format!("{}:{}", self.config.ebay.client_id, self.config.ebay.client_secret);
        let basic_auth = format!("Basic {}", base64::Engine::encode(&base64::prelude::BASE64_STANDARD, auth));

        let res = self.http_client.post(self.identity_url())
            .header("Authorization", basic_auth)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .body(format!(
                "grant_type=refresh_token&refresh_token={}&scope=https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/buy.watchlist",
                refresh_token
            ))
            .send()?;

        if !res.status().is_success() {
            return Err(Error::OAuth(format!("Failed to refresh token: HTTP {}", res.status())));
        }

        let body: Value = res.json()?;
        let access_token = body["access_token"].as_str().ok_or_else(|| Error::OAuth("No access token".into()))?.to_string();
        let expires_in = body["expires_in"].as_i64().ok_or_else(|| Error::OAuth("No expires_in".into()))?;
        let expires_at = Utc::now().timestamp() + expires_in;

        Ok(OAuthToken {
            access_token,
            refresh_token: refresh_token.to_string(),
            expires_at,
        })
    }

    fn fetch_my_ebay_buying(&self, token: &str) -> Result<(Vec<Item>, Vec<SavedSearch>)> {
        let xml_body = format!(
            r#"<?xml version="1.0" encoding="utf-8"?>
            <GetMyeBayBuyingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <RequesterCredentials>
                <eBayAuthToken>{}</eBayAuthToken>
              </RequesterCredentials>
              <WatchList>
                <ActiveList>
                  <Sort>TimeLeft</Sort>
                </ActiveList>
              </WatchList>
              <SavedSearches>
                <SearchList>true</SearchList>
              </SavedSearches>
            </GetMyeBayBuyingRequest>"#,
            token
        );

        let res = self.http_client.post(self.trading_url())
            .header("X-EBAY-API-COMPATIBILITY-LEVEL", "1357")
            .header("X-EBAY-API-DEV-NAME", "DEV_NAME")
            .header("X-EBAY-API-APP-NAME", &self.config.ebay.client_id)
            .header("X-EBAY-API-CERT-NAME", &self.config.ebay.client_secret)
            .header("X-EBAY-API-CALL-NAME", "GetMyeBayBuying")
            .header("X-EBAY-API-SITEID", "0")
            .header("Content-Type", "text/xml")
            .body(xml_body)
            .send()?;

        let response_text = res.text()?;
        parse_get_my_ebay_buying(&response_text)
    }

    fn search_items(&self, token: &str, query: &str) -> Result<Vec<ItemSummary>> {
        let url = format!("{}/item_summary/search?q={}", self.browse_url(), urlencoding::encode(query));
        let res = self.http_client.get(url)
            .header("Authorization", format!("Bearer {}", token))
            .send()?;

        if !res.status().is_success() {
            return Err(Error::Http(res.error_for_status().unwrap_err()));
        }

        let body: Value = res.json()?;
        let mut summaries = Vec::new();
        if let Some(items) = body["itemSummaries"].as_array() {
            for item in items {
                let id = item["itemId"].as_str().unwrap_or_default().to_string();
                let title = item["title"].as_str().unwrap_or_default().to_string();
                let price = item["price"]["value"].as_str().unwrap_or("0.0").parse::<f64>().unwrap_or(0.0);
                let shipping = item["shippingOptions"][0]["shippingCost"]["value"].as_str().unwrap_or("0.0").parse::<f64>().unwrap_or(0.0);
                let buy_it_now = item["marketingPrice"]["originalPrice"]["value"].as_str().map(|s| s.parse::<f64>().unwrap_or(0.0));
                
                // Parse date string
                let end_time_str = item["itemEndDate"].as_str().unwrap_or_default();
                let end_time = chrono::DateTime::parse_from_rfc3339(end_time_str)
                    .map(|dt| dt.timestamp())
                    .unwrap_or(0);

                summaries.push(ItemSummary { id, title, price, shipping, buy_it_now, end_time });
            }
        }

        Ok(summaries)
    }

    fn place_bid(&self, token: &str, item_id: &str, amount: f64) -> Result<BidResult> {
        let xml_body = format!(
            r#"<?xml version="1.0" encoding="utf-8"?>
            <PlaceOfferRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <RequesterCredentials>
                <eBayAuthToken>{}</eBayAuthToken>
              </RequesterCredentials>
              <ItemID>{}</ItemID>
              <Offer>
                <Action>Bid</Action>
                <MaxBid currencyID="USD">{}</MaxBid>
                <Quantity>1</Quantity>
              </Offer>
            </PlaceOfferRequest>"#,
            token, item_id, amount
        );

        let res = self.http_client.post(self.trading_url())
            .header("X-EBAY-API-COMPATIBILITY-LEVEL", "1357")
            .header("X-EBAY-API-DEV-NAME", "DEV_NAME")
            .header("X-EBAY-API-APP-NAME", &self.config.ebay.client_id)
            .header("X-EBAY-API-CERT-NAME", &self.config.ebay.client_secret)
            .header("X-EBAY-API-CALL-NAME", "PlaceOffer")
            .header("X-EBAY-API-SITEID", "0")
            .header("Content-Type", "text/xml")
            .body(xml_body)
            .send()?;

        let response_text = res.text()?;
        parse_place_offer(&response_text)
    }
}

// Helper functions for parsing XML responses safely
fn extract_tag_content(xml: &str, tag: &str) -> Option<String> {
    let start_tag = format!("<{}>", tag);
    let end_tag = format!("</{}>", tag);
    let start_idx = xml.find(&start_tag)?;
    let end_idx = xml.find(&end_tag)?;
    if start_idx < end_idx {
        Some(xml[start_idx + start_tag.len()..end_idx].trim().to_string())
    } else {
        None
    }
}

fn extract_elements(xml: &str, tag: &str) -> Vec<String> {
    let start_tag = format!("<{}>", tag);
    let end_tag = format!("</{}>", tag);
    let mut elements = Vec::new();
    let mut current = xml;
    while let Some(start_idx) = current.find(&start_tag) {
        if let Some(end_idx) = current.find(&end_tag) {
            let element = current[start_idx + start_tag.len()..end_idx].trim().to_string();
            elements.push(element);
            current = &current[end_idx + end_tag.len()..];
        } else {
            break;
        }
    }
    elements
}

fn parse_get_my_ebay_buying(xml: &str) -> Result<(Vec<Item>, Vec<SavedSearch>)> {
    let ack = extract_tag_content(xml, "Ack").unwrap_or_default();
    if ack != "Success" && ack != "Warning" {
        let error_msg = extract_tag_content(xml, "LongMessage").unwrap_or_else(|| "Unknown Trading API error".to_string());
        return Err(Error::Xml(error_msg));
    }

    let mut items = Vec::new();
    let mut saved_searches = Vec::new();

    // Parse items
    let item_nodes = extract_elements(xml, "Item");
    for node in item_nodes {
        let id = extract_tag_content(&node, "ItemID").unwrap_or_default();
        let title = extract_tag_content(&node, "Title").unwrap_or_default();
        let current_price = extract_tag_content(&node, "ConvertedCurrentPrice").unwrap_or_default().parse::<f64>().unwrap_or(0.0);
        let shipping_cost = extract_tag_content(&node, "ShippingServiceCost").unwrap_or_default().parse::<f64>().unwrap_or(0.0);
        let buy_it_now_price = extract_tag_content(&node, "BuyItNowPrice").map(|s| s.parse::<f64>().unwrap_or(0.0));
        let end_time_str = extract_tag_content(&node, "EndTime").unwrap_or_default();
        let end_time = chrono::DateTime::parse_from_rfc3339(&end_time_str)
            .map(|dt| dt.timestamp())
            .unwrap_or(0);

        if !id.is_empty() {
            items.push(Item { id, title, current_price, shipping_cost, buy_it_now_price, end_time });
        }
    }

    // Parse saved searches
    let search_nodes = extract_elements(xml, "SearchList");
    for node in search_nodes {
        let name = extract_tag_content(&node, "SearchName").unwrap_or_default();
        let query = extract_tag_content(&node, "QueryKeywords").unwrap_or_default();
        if !name.is_empty() && !query.is_empty() {
            saved_searches.push(SavedSearch { name, query });
        }
    }

    Ok((items, saved_searches))
}

fn parse_place_offer(xml: &str) -> Result<BidResult> {
    let ack = extract_tag_content(xml, "Ack").unwrap_or_default();
    if ack == "Success" || ack == "Warning" {
        Ok(BidResult {
            success: true,
            transaction_id: extract_tag_content(xml, "TransactionID"),
            error_message: None,
        })
    } else {
        let error_msg = extract_tag_content(xml, "LongMessage").unwrap_or_else(|| "Unknown Bidding API error".to_string());
        Ok(BidResult {
            success: false,
            transaction_id: None,
            error_message: Some(error_msg),
        })
    }
}

// Mock Client for tests
pub struct MockEbayClient {
    pub items: Arc<std::sync::Mutex<Vec<Item>>>,
    pub saved_searches: Arc<std::sync::Mutex<Vec<SavedSearch>>>,
    pub bid_results: Arc<std::sync::Mutex<Vec<BidResult>>>,
}

impl MockEbayClient {
    pub fn new() -> Self {
        Self {
            items: Arc::new(std::sync::Mutex::new(Vec::new())),
            saved_searches: Arc::new(std::sync::Mutex::new(Vec::new())),
            bid_results: Arc::new(std::sync::Mutex::new(Vec::new())),
        }
    }
}

impl EbayClient for MockEbayClient {
    fn get_token(&self, _code: &str) -> Result<OAuthToken> {
        Ok(OAuthToken {
            access_token: "mock-access-token".to_string(),
            refresh_token: "mock-refresh-token".to_string(),
            expires_at: Utc::now().timestamp() + 3600,
        })
    }

    fn refresh_token(&self, refresh_token: &str) -> Result<OAuthToken> {
        Ok(OAuthToken {
            access_token: "mock-new-access-token".to_string(),
            refresh_token: refresh_token.to_string(),
            expires_at: Utc::now().timestamp() + 3600,
        })
    }

    fn fetch_my_ebay_buying(&self, _token: &str) -> Result<(Vec<Item>, Vec<SavedSearch>)> {
        let items = self.items.lock().unwrap().clone();
        let searches = self.saved_searches.lock().unwrap().clone();
        Ok((items, searches))
    }

    fn search_items(&self, _token: &str, _query: &str) -> Result<Vec<ItemSummary>> {
        let items = self.items.lock().unwrap();
        Ok(items.iter().map(|i| ItemSummary {
            id: i.id.clone(),
            title: i.title.clone(),
            price: i.current_price,
            shipping: i.shipping_cost,
            buy_it_now: i.buy_it_now_price,
            end_time: i.end_time,
        }).collect())
    }

    fn place_bid(&self, _token: &str, _item_id: &str, _amount: f64) -> Result<BidResult> {
        let mut results = self.bid_results.lock().unwrap();
        if results.is_empty() {
            Ok(BidResult {
                success: true,
                transaction_id: Some("mock-txn-id".to_string()),
                error_message: None,
            })
        } else {
            Ok(results.remove(0))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_xml_parsing_buying_data() {
        let sample_xml = r#"<?xml version="1.0" encoding="utf-8"?>
        <GetMyeBayBuyingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
          <Ack>Success</Ack>
          <WatchList>
            <ItemArray>
              <Item>
                <ItemID>110022334455</ItemID>
                <Title>Classic Watch</Title>
                <ConvertedCurrentPrice>25.00</ConvertedCurrentPrice>
                <ShippingServiceCost>4.99</ShippingServiceCost>
                <EndTime>2026-06-15T12:00:00.000Z</EndTime>
                <BuyItNowPrice>35.00</BuyItNowPrice>
              </Item>
            </ItemArray>
          </WatchList>
          <SavedSearchList>
            <SearchList>
              <SearchName>vintage watches</SearchName>
              <QueryKeywords>vintage watch</QueryKeywords>
            </SearchList>
          </SavedSearchList>
        </GetMyeBayBuyingResponse>"#;

        let (items, searches) = parse_get_my_ebay_buying(sample_xml).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].id, "110022334455");
        assert_eq!(items[0].title, "Classic Watch");
        assert_eq!(items[0].current_price, 25.0);
        assert_eq!(items[0].shipping_cost, 4.99);
        assert_eq!(items[0].buy_it_now_price, Some(35.0));

        assert_eq!(searches.len(), 1);
        assert_eq!(searches[0].name, "vintage watches");
        assert_eq!(searches[0].query, "vintage watch");
    }

    #[test]
    fn test_xml_parsing_place_offer_success() {
        let sample_xml = r#"<?xml version="1.0" encoding="utf-8"?>
        <PlaceOfferResponse xmlns="urn:ebay:apis:eBLBaseComponents">
          <Ack>Success</Ack>
          <TransactionID>txn12345</TransactionID>
        </PlaceOfferResponse>"#;

        let result = parse_place_offer(sample_xml).unwrap();
        assert!(result.success);
        assert_eq!(result.transaction_id, Some("txn12345".to_string()));
        assert!(result.error_message.is_none());
    }

    #[test]
    fn test_xml_parsing_place_offer_failure() {
        let sample_xml = r#"<?xml version="1.0" encoding="utf-8"?>
        <PlaceOfferResponse xmlns="urn:ebay:apis:eBLBaseComponents">
          <Ack>Failure</Ack>
          <Errors>
            <LongMessage>Price too low or bidding ended</LongMessage>
          </Errors>
        </PlaceOfferResponse>"#;

        let result = parse_place_offer(sample_xml).unwrap();
        assert!(!result.success);
        assert!(result.transaction_id.is_none());
        assert_eq!(result.error_message, Some("Price too low or bidding ended".to_string()));
    }
}
