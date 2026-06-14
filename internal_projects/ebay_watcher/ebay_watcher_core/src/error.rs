use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("TOML parsing error: {0}")]
    Toml(#[from] toml::de::Error),

    #[error("Database error: {0}")]
    Database(#[from] rusqlite::Error),

    #[error("HTTP client error: {0}")]
    Http(#[from] reqwest::Error),

    #[error("XML parsing error: {0}")]
    Xml(String),

    #[error("OAuth error: {0}")]
    OAuth(String),

    #[error("Configuration error: {0}")]
    Configuration(String),
}

impl Error {
    pub fn is_transient(&self) -> bool {
        match self {
            Self::Http(e) => {
                if e.is_timeout() || e.is_connect() {
                    return true;
                }
                if let Some(status) = e.status() {
                    return status.is_server_error() || status.as_u16() == 429;
                }
                true
            }
            Self::Io(_) => true,
            _ => false,
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_is_transient() {
        let io_err = Error::Io(std::io::Error::new(std::io::ErrorKind::ConnectionAborted, "connection aborted"));
        assert!(io_err.is_transient());

        let conf_err = Error::Configuration("invalid option".to_string());
        assert!(!conf_err.is_transient());
    }
}
