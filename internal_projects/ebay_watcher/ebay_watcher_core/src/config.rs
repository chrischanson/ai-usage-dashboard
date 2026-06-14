use serde::Deserialize;
use std::fs;
use std::path::Path;
use crate::error::Result;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub ebay: EbayConfig,
    pub sync: SyncConfig,
    pub sniper: SniperConfig,
    pub database: DatabaseConfig,
    #[serde(default)]
    pub deals: DealsConfig,
}

#[derive(Clone, Deserialize)]
pub struct EbayConfig {
    pub client_id: String,
    pub client_secret: String,
    pub ru_name: String,
    /// Developer Name from the eBay Developer Portal (X-EBAY-API-DEV-NAME header).
    #[serde(default)]
    pub dev_name: String,
    #[serde(default = "default_sandbox")]
    pub sandbox: bool,
}

impl std::fmt::Debug for EbayConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EbayConfig")
            .field("client_id", &self.client_id)
            .field("client_secret", &"<REDACTED>")
            .field("ru_name", &self.ru_name)
            .field("dev_name", &self.dev_name)
            .field("sandbox", &self.sandbox)
            .finish()
    }
}


#[derive(Debug, Clone, Deserialize)]
pub struct SyncConfig {
    #[serde(default = "default_poll_interval")]
    pub poll_interval_seconds: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SniperConfig {
    #[serde(default = "default_lead_time")]
    pub lead_time_seconds: u64,
    #[serde(default = "default_fallback")]
    pub fallback_to_trading_api: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DatabaseConfig {
    #[serde(default = "default_db_path")]
    pub db_path: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DealsConfig {
    #[serde(default = "default_max_total_price")]
    pub max_total_price: f64,
}

impl Default for DealsConfig {
    fn default() -> Self {
        Self {
            max_total_price: default_max_total_price(),
        }
    }
}

fn default_sandbox() -> bool { true }
fn default_max_total_price() -> f64 { 100.0 }
fn default_poll_interval() -> u64 { 300 }
fn default_lead_time() -> u64 { 5 }
fn default_fallback() -> bool { true }
fn default_db_path() -> String { "ebay_watcher.db".to_string() }

impl Config {
    pub fn load_from_str(s: &str) -> Result<Self> {
        let config: Config = toml::from_str(s)?;
        Ok(config)
    }

    pub fn load_from_file<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = fs::read_to_string(path)?;
        Self::load_from_str(&content)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_valid_config() {
        let toml_str = r#"
            [ebay]
            client_id = "test-id"
            client_secret = "test-secret"
            ru_name = "test-runame"
            sandbox = false

            [sync]
            poll_interval_seconds = 60

            [sniper]
            lead_time_seconds = 3
            fallback_to_trading_api = false

            [database]
            db_path = "test.db"
        "#;
        let config = Config::load_from_str(toml_str).unwrap();
        assert_eq!(config.ebay.client_id, "test-id");
        assert_eq!(config.ebay.client_secret, "test-secret");
        assert_eq!(config.ebay.ru_name, "test-runame");
        assert!(!config.ebay.sandbox);
        assert_eq!(config.sync.poll_interval_seconds, 60);
        assert_eq!(config.sniper.lead_time_seconds, 3);
        assert!(!config.sniper.fallback_to_trading_api);
        assert_eq!(config.database.db_path, "test.db");
    }

    #[test]
    fn test_parse_config_defaults() {
        let toml_str = r#"
            [ebay]
            client_id = "test-id"
            client_secret = "test-secret"
            ru_name = "test-runame"

            [sync]

            [sniper]

            [database]
        "#;
        let config = Config::load_from_str(toml_str).unwrap();
        assert!(config.ebay.sandbox); // default
        assert_eq!(config.sync.poll_interval_seconds, 300); // default
        assert_eq!(config.sniper.lead_time_seconds, 5); // default
        assert!(config.sniper.fallback_to_trading_api); // default
        assert_eq!(config.database.db_path, "ebay_watcher.db"); // default
    }

    #[test]
    fn test_ebay_config_debug_redaction() {
        let config = EbayConfig {
            client_id: "my-client-id".to_string(),
            client_secret: "my-secret-key-12345".to_string(),
            ru_name: "my-ru-name".to_string(),
            dev_name: "my-dev-name".to_string(),
            sandbox: true,
        };
        let debug_str = format!("{:?}", config);
        assert!(!debug_str.contains("my-secret-key-12345"), "Secret key was not redacted in Debug output");
        assert!(debug_str.contains("<REDACTED>"), "Redaction placeholder was not found in Debug output");
        assert!(debug_str.contains("my-client-id"), "Other fields were incorrectly redacted or missing");
    }
}
