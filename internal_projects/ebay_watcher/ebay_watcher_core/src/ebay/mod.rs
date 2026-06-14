pub mod client;

pub use client::{EbayClient, RealEbayClient};
#[cfg(any(test, feature = "mock"))]
pub use client::MockEbayClient;
