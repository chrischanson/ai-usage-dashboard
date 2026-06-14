#[cfg(any(test, feature = "mock"))]
use std::sync::Arc;
use chrono::Utc;
use serde_json::Value;
use crate::config::Config;
use crate::error::{Error, Result};
use crate::models::{OAuthToken, Item, SavedSearch, ItemSummary, BidResult};

pub trait EbayClient: Send + Sync {
    fn get_token(&self, code: &str) -> impl std::future::Future<Output = Result<OAuthToken>> + Send;
    fn refresh_token(&self, refresh_token: &str) -> impl std::future::Future<Output = Result<OAuthToken>> + Send;
    fn fetch_my_ebay_buying(&self, token: &str) -> impl std::future::Future<Output = Result<(Vec<Item>, Vec<SavedSearch>)>> + Send;
    fn search_items(&self, token: &str, query: &str) -> impl std::future::Future<Output = Result<Vec<ItemSummary>>> + Send;
    fn place_bid(&self, token: &str, item_id: &str, amount: f64) -> impl std::future::Future<Output = Result<BidResult>> + Send;
}

#[derive(Clone)]
pub struct RealEbayClient {
    config: Config,
    http_client: reqwest::Client,
}

impl RealEbayClient {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            http_client: reqwest::Client::new(),
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
    fn get_token(&self, code: &str) -> impl std::future::Future<Output = Result<OAuthToken>> + Send {
        let code = code.to_string();
        let client = self.clone();
        async move {
            let auth = format!("{}:{}", client.config.ebay.client_id, client.config.ebay.client_secret);
            let basic_auth = format!("Basic {}", base64::Engine::encode(&base64::prelude::BASE64_STANDARD, auth));

            let res = client.http_client.post(client.identity_url())
                .header("Authorization", basic_auth)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .body(format!(
                    "grant_type=authorization_code&code={}&redirect_uri={}",
                    code, client.config.ebay.ru_name
                ))
                .send()
                .await?;

            if !res.status().is_success() {
                return Err(Error::OAuth(format!("Failed to get token: HTTP {}", res.status())));
            }

            let body: Value = res.json().await?;
            let access_token = body["access_token"].as_str().ok_or_else(|| Error::OAuth("No access token".into()))?.to_string();
            let refresh_token = body["refresh_token"].as_str().ok_or_else(|| Error::OAuth("No refresh token".into()))?.to_string();
            let expires_in = body["expires_in"].as_i64().ok_or_else(|| Error::OAuth("No expires_in".into()))?;
            let expires_at = Utc::now().timestamp() + expires_in;

            Ok(OAuthToken { access_token, refresh_token, expires_at })
        }
    }

    fn refresh_token(&self, refresh_token: &str) -> impl std::future::Future<Output = Result<OAuthToken>> + Send {
        let refresh_token = refresh_token.to_string();
        let client = self.clone();
        async move {
            let auth = format!("{}:{}", client.config.ebay.client_id, client.config.ebay.client_secret);
            let basic_auth = format!("Basic {}", base64::Engine::encode(&base64::prelude::BASE64_STANDARD, auth));

            let res = client.http_client.post(client.identity_url())
                .header("Authorization", basic_auth)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .body(format!(
                    "grant_type=refresh_token&refresh_token={}&scope=https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/buy.watchlist",
                    refresh_token
                ))
                .send()
                .await?;

            if !res.status().is_success() {
                return Err(Error::OAuth(format!("Failed to refresh token: HTTP {}", res.status())));
            }

            let body: Value = res.json().await?;
            let access_token = body["access_token"].as_str().ok_or_else(|| Error::OAuth("No access token".into()))?.to_string();
            let expires_in = body["expires_in"].as_i64().ok_or_else(|| Error::OAuth("No expires_in".into()))?;
            let expires_at = Utc::now().timestamp() + expires_in;

            Ok(OAuthToken {
                access_token,
                refresh_token: refresh_token.to_string(),
                expires_at,
            })
        }
    }

    fn fetch_my_ebay_buying(&self, token: &str) -> impl std::future::Future<Output = Result<(Vec<Item>, Vec<SavedSearch>)>> + Send {
        let token = token.to_string();
        let client = self.clone();
        async move {
            let xml_body = build_get_my_ebay_buying_xml(&token);

            let res = client.http_client.post(client.trading_url())
                .header("X-EBAY-API-COMPATIBILITY-LEVEL", "1357")
                .header("X-EBAY-API-DEV-NAME", &client.config.ebay.dev_name)
                .header("X-EBAY-API-APP-NAME", &client.config.ebay.client_id)
                .header("X-EBAY-API-CERT-NAME", &client.config.ebay.client_secret)
                .header("X-EBAY-API-CALL-NAME", "GetMyeBayBuying")
                .header("X-EBAY-API-SITEID", "0")
                .header("Content-Type", "text/xml")
                .body(xml_body)
                .send()
                .await?;

            let response_text = res.text().await?;
            parse_get_my_ebay_buying(&response_text)
        }
    }

    fn search_items(&self, token: &str, query: &str) -> impl std::future::Future<Output = Result<Vec<ItemSummary>>> + Send {
        let token = token.to_string();
        let query = query.to_string();
        let client = self.clone();
        async move {
            let url = format!("{}/item_summary/search?q={}", client.browse_url(), urlencoding::encode(&query));
            let res = client.http_client.get(url)
                .header("Authorization", format!("Bearer {}", token))
                .send()
                .await?;

            if !res.status().is_success() {
                return Err(Error::Http(res.error_for_status().unwrap_err()));
            }

            let body: Value = res.json().await?;
            parse_search_items_json(&body)
        }
    }

    fn place_bid(&self, token: &str, item_id: &str, amount: f64) -> impl std::future::Future<Output = Result<BidResult>> + Send {
        let token = token.to_string();
        let item_id = item_id.to_string();
        let client = self.clone();
        async move {
            let xml_body = build_place_offer_xml(&token, &item_id, amount);

            let res = client.http_client.post(client.trading_url())
                .header("X-EBAY-API-COMPATIBILITY-LEVEL", "1357")
                .header("X-EBAY-API-DEV-NAME", &client.config.ebay.dev_name)
                .header("X-EBAY-API-APP-NAME", &client.config.ebay.client_id)
                .header("X-EBAY-API-CERT-NAME", &client.config.ebay.client_secret)
                .header("X-EBAY-API-CALL-NAME", "PlaceOffer")
                .header("X-EBAY-API-SITEID", "0")
                .header("Content-Type", "text/xml")
                .body(xml_body)
                .send()
                .await?;

            let response_text = res.text().await?;
            parse_place_offer(&response_text)
        }
    }
}

// Builds the GetMyeBayBuying XML request body. The OAuth token is XML-escaped via
// `quick_xml::escape::escape` to prevent injection from tampered or malformed DB values.
fn build_get_my_ebay_buying_xml(token: &str) -> String {
    let safe_token = quick_xml::escape::escape(token);
    format!(r#"<?xml version="1.0" encoding="utf-8"?>
            <GetMyeBayBuyingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <RequesterCredentials>
                <eBayAuthToken>{safe_token}</eBayAuthToken>
              </RequesterCredentials>
              <WatchList>
                <ActiveList>
                  <Sort>TimeLeft</Sort>
                </ActiveList>
              </WatchList>
              <SavedSearches>
                <SearchList>true</SearchList>
              </SavedSearches>
            </GetMyeBayBuyingRequest>"#)
}

// Builds the PlaceOffer XML request body. Both the OAuth token and item ID are
// XML-escaped. `amount` is an f64 and its formatted representation cannot carry
// XML special characters.
fn build_place_offer_xml(token: &str, item_id: &str, amount: f64) -> String {
    let safe_token = quick_xml::escape::escape(token);
    let safe_item_id = quick_xml::escape::escape(item_id);
    format!(r#"<?xml version="1.0" encoding="utf-8"?>
            <PlaceOfferRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <RequesterCredentials>
                <eBayAuthToken>{safe_token}</eBayAuthToken>
              </RequesterCredentials>
              <ItemID>{safe_item_id}</ItemID>
              <Offer>
                <Action>Bid</Action>
                <MaxBid currencyID="USD">{amount:.2}</MaxBid>
                <Quantity>1</Quantity>
              </Offer>
            </PlaceOfferRequest>"#)
}

fn parse_search_items_json(body: &serde_json::Value) -> Result<Vec<ItemSummary>> {
    let mut summaries = Vec::new();
    if let Some(items) = body["itemSummaries"].as_array() {
        for item in items {
            let id = item["itemId"].as_str().unwrap_or_default().to_string();
            let title = item["title"].as_str().unwrap_or_default().to_string();
            let price = item.get("price")
                .and_then(|p| p.get("value"))
                .and_then(|val| val.as_str())
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(0.0);
            let shipping = item.get("shippingOptions")
                .and_then(|so| so.as_array())
                .and_then(|arr| arr.first())
                .and_then(|opt| opt.get("shippingCost"))
                .and_then(|cost| cost.get("value"))
                .and_then(|val| val.as_str())
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(0.0);
            let buy_it_now = item.get("marketingPrice")
                .and_then(|mp| mp.get("originalPrice"))
                .and_then(|op| op.get("value"))
                .and_then(|val| val.as_str())
                .and_then(|s| s.parse::<f64>().ok());
            let end_time_str = item["itemEndDate"].as_str().unwrap_or_default();
            let end_time = chrono::DateTime::parse_from_rfc3339(end_time_str)
                .map(|dt| dt.timestamp())
                .unwrap_or(0);
            summaries.push(ItemSummary { id, title, price, shipping, buy_it_now, end_time });
        }
    }
    Ok(summaries)
}

// Parses the GetMyeBayBuying response with quick-xml's event reader.
// The path-stack approach correctly handles nested same-named elements and
// XML entities, unlike the previous hand-rolled string scanner.
fn parse_get_my_ebay_buying(xml: &str) -> Result<(Vec<Item>, Vec<SavedSearch>)> {
    use quick_xml::events::Event;
    use quick_xml::Reader;

    let mut reader = Reader::from_str(xml);
    reader.trim_text(true);

    let mut ack = String::new();
    let mut error_msg = String::new();
    let mut items: Vec<Item> = Vec::new();
    let mut saved_searches: Vec<SavedSearch> = Vec::new();

    // Path stack — tracks element context so we know when we're inside
    // WatchList vs SavedSearchList without fragile string searching.
    let mut path: Vec<String> = Vec::new();
    let mut cur_item: Option<Item> = None;
    let mut cur_search: Option<SavedSearch> = None;

    loop {
        match reader.read_event() {
            Ok(Event::Start(e)) => {
                let tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                if tag == "Item" && path.iter().any(|t| t == "WatchList") {
                    cur_item = Some(Item {
                        id: String::new(), title: String::new(),
                        current_price: 0.0, shipping_cost: 0.0,
                        buy_it_now_price: None, end_time: 0,
                    });
                }
                if tag == "SearchList" && path.iter().any(|t| t == "SavedSearchList") {
                    cur_search = Some(SavedSearch { name: String::new(), query: String::new() });
                }
                path.push(tag);
            }
            Ok(Event::Text(e)) => {
                let text = e.unescape().map(|s| s.into_owned()).unwrap_or_default();
                let tag = path.last().map(|s| s.as_str()).unwrap_or("");
                if tag == "Ack" && path.len() == 2 {
                    ack = text;
                } else if tag == "LongMessage" && error_msg.is_empty() {
                    error_msg = text;
                } else if let Some(ref mut item) = cur_item {
                    match tag {
                        "ItemID"                => item.id = text,
                        "Title"                 => item.title = text,
                        "ConvertedCurrentPrice" => item.current_price = text.parse().unwrap_or(0.0),
                        "ShippingServiceCost"   => item.shipping_cost = text.parse().unwrap_or(0.0),
                        "BuyItNowPrice"         => item.buy_it_now_price = text.parse().ok(),
                        "EndTime" => {
                            item.end_time = chrono::DateTime::parse_from_rfc3339(&text)
                                .map(|dt| dt.timestamp())
                                .unwrap_or(0);
                        }
                        _ => {}
                    }
                } else if let Some(ref mut search) = cur_search {
                    match tag {
                        "SearchName"    => search.name = text,
                        "QueryKeywords" => search.query = text,
                        _ => {}
                    }
                }
            }
            Ok(Event::End(e)) => {
                let tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                if tag == "Item" {
                    if let Some(item) = cur_item.take() {
                        if !item.id.is_empty() { items.push(item); }
                    }
                }
                if tag == "SearchList" {
                    if let Some(search) = cur_search.take() {
                        if !search.name.is_empty() && !search.query.is_empty() {
                            saved_searches.push(search);
                        }
                    }
                }
                path.pop();
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(Error::Xml(e.to_string())),
            _ => {}
        }
    }

    if ack != "Success" && ack != "Warning" {
        let msg = if error_msg.is_empty() {
            "Unknown Trading API error".to_string()
        } else {
            error_msg
        };
        return Err(Error::Xml(msg));
    }
    Ok((items, saved_searches))
}

// Parses the PlaceOffer response with quick-xml's event reader.
fn parse_place_offer(xml: &str) -> Result<BidResult> {
    use quick_xml::events::Event;
    use quick_xml::Reader;

    let mut reader = Reader::from_str(xml);
    reader.trim_text(true);

    let mut ack = String::new();
    let mut transaction_id: Option<String> = None;
    let mut error_msg: Option<String> = None;
    let mut current_tag = String::new();

    loop {
        match reader.read_event() {
            Ok(Event::Start(e)) => {
                current_tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
            }
            Ok(Event::Text(e)) => {
                let text = e.unescape().map(|s| s.into_owned()).unwrap_or_default();
                match current_tag.as_str() {
                    "Ack"           => ack = text,
                    "TransactionID" => transaction_id = Some(text),
                    "LongMessage"   => { if error_msg.is_none() { error_msg = Some(text); } }
                    _ => {}
                }
            }
            Ok(Event::End(_)) => current_tag.clear(),
            Ok(Event::Eof) => break,
            Err(e) => return Err(Error::Xml(e.to_string())),
            _ => {}
        }
    }

    if ack == "Success" || ack == "Warning" {
        Ok(BidResult { success: true, transaction_id, error_message: None })
    } else {
        Ok(BidResult {
            success: false,
            transaction_id: None,
            error_message: Some(error_msg.unwrap_or_else(|| "Unknown Bidding API error".to_string())),
        })
    }
}

// Mock Client for tests
#[cfg(any(test, feature = "mock"))]
#[derive(Clone)]
pub struct MockEbayClient {
    pub items: Arc<std::sync::Mutex<Vec<Item>>>,
    pub saved_searches: Arc<std::sync::Mutex<Vec<SavedSearch>>>,
    pub bid_results: Arc<std::sync::Mutex<Vec<BidResult>>>,
}

#[cfg(any(test, feature = "mock"))]
impl MockEbayClient {
    pub fn new() -> Self {
        Self {
            items: Arc::new(std::sync::Mutex::new(Vec::new())),
            saved_searches: Arc::new(std::sync::Mutex::new(Vec::new())),
            bid_results: Arc::new(std::sync::Mutex::new(Vec::new())),
        }
    }
}

#[cfg(any(test, feature = "mock"))]
impl EbayClient for MockEbayClient {
    fn get_token(&self, _code: &str) -> impl std::future::Future<Output = Result<OAuthToken>> + Send {
        async move {
            Ok(OAuthToken {
                access_token: "mock-access-token".to_string(),
                refresh_token: "mock-refresh-token".to_string(),
                expires_at: Utc::now().timestamp() + 3600,
            })
        }
    }

    fn refresh_token(&self, refresh_token: &str) -> impl std::future::Future<Output = Result<OAuthToken>> + Send {
        let refresh_token = refresh_token.to_string();
        async move {
            Ok(OAuthToken {
                access_token: "mock-new-access-token".to_string(),
                refresh_token,
                expires_at: Utc::now().timestamp() + 3600,
            })
        }
    }

    fn fetch_my_ebay_buying(&self, _token: &str) -> impl std::future::Future<Output = Result<(Vec<Item>, Vec<SavedSearch>)>> + Send {
        let searches = self.saved_searches.lock().unwrap().clone();
        async move {
            Ok((Vec::new(), searches))
        }
    }

    fn search_items(&self, _token: &str, _query: &str) -> impl std::future::Future<Output = Result<Vec<ItemSummary>>> + Send {
        let items = self.items.lock().unwrap().clone();
        async move {
            Ok(items.iter().map(|i| ItemSummary {
                id: i.id.clone(),
                title: i.title.clone(),
                price: i.current_price,
                shipping: i.shipping_cost,
                buy_it_now: i.buy_it_now_price,
                end_time: i.end_time,
            }).collect())
        }
    }

    fn place_bid(&self, _token: &str, _item_id: &str, _amount: f64) -> impl std::future::Future<Output = Result<BidResult>> + Send {
        let mut results = self.bid_results.lock().unwrap();
        let result = if results.is_empty() {
            BidResult {
                success: true,
                transaction_id: Some("mock-txn-id".to_string()),
                error_message: None,
            }
        } else {
            results.remove(0)
        };
        async move {
            Ok(result)
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

    #[test]
    fn test_json_parsing_search_items_missing_fields() {
        let sample_json = serde_json::json!({
            "itemSummaries": [
                {
                    "itemId": "v1|110022334455|0",
                    "title": "Vintage Watch",
                    "price": {
                        "value": "45.50",
                        "currency": "USD"
                    },
                    "shippingOptions": [
                        {
                            "shippingCost": {
                                "value": "5.00",
                                "currency": "USD"
                            }
                        }
                    ],
                    "marketingPrice": {
                        "originalPrice": {
                            "value": "60.00",
                            "currency": "USD"
                        }
                    },
                    "itemEndDate": "2026-06-15T12:00:00.000Z"
                },
                {
                    "itemId": "v1|999999999999|0",
                    "title": "Minimal Info Item"
                }
            ]
        });

        let results = parse_search_items_json(&sample_json).unwrap();
        assert_eq!(results.len(), 2);

        // First item
        assert_eq!(results[0].id, "v1|110022334455|0");
        assert_eq!(results[0].title, "Vintage Watch");
        assert_eq!(results[0].price, 45.50);
        assert_eq!(results[0].shipping, 5.00);
        assert_eq!(results[0].buy_it_now, Some(60.00));
        assert_eq!(results[0].end_time, chrono::DateTime::parse_from_rfc3339("2026-06-15T12:00:00.000Z").unwrap().timestamp());

        // Second item
        assert_eq!(results[1].id, "v1|999999999999|0");
        assert_eq!(results[1].title, "Minimal Info Item");
        assert_eq!(results[1].price, 0.0);
        assert_eq!(results[1].shipping, 0.0);
        assert_eq!(results[1].buy_it_now, None);
        assert_eq!(results[1].end_time, 0);
    }
}

