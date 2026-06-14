# eBay Watcher & Snipe Bidder

A multi-crate Rust workspace comprising a background scheduling daemon and a premium terminal interface (TUI) for watching eBay items, tracking saved searches, discovering deals, and scheduling automatic last-second bid snipes.

## Workspace Architecture

The project is structured into three crates:

*   **[`ebay_watcher_core`](file:///home/dev/workspace/main/internal_projects/ebay_watcher/ebay_watcher_core)**: Shared library crate containing the data models, rusqlite SQLite database migrations and queries, configuration loaders (supporting debug-log credential redaction), and the async `EbayClient` API implementation (supporting XML Trading API requests, JSON Browse API searches, and mock implementations for testing).
*   **[`ebay_watcher_daemon`](file:///home/dev/workspace/main/internal_projects/ebay_watcher/ebay_watcher_daemon)**: Background daemon running token-refresh routines, periodic sync schedules for watchlists/saved searches, and an exact-second proxy bid scheduler (`scheduler.rs`) that executes snipes at a configured lead time prior to auction close. Supports immediate polling triggers via `SIGUSR1` and clean shutdown via `SIGINT`/`SIGTERM`.
*   **[`ebay_watcher_tui`](file:///home/dev/workspace/main/internal_projects/ebay_watcher/ebay_watcher_tui)**: Interactive `ratatui`-based console dashboard to monitor watched items, filter deals under a price threshold, schedule new snipes, and cancel pending snipes (using hotkey `x` which signals the daemon immediately).

---

## Configuration

To get started, copy the configuration template to a local configuration file:

```bash
cp config.example.toml config.toml
```

Edit `config.toml` with your credentials and preferences:

```toml
[ebay]
# Application credentials from the eBay Developer Portal
client_id = "YOUR_CLIENT_ID_HERE"
client_secret = "YOUR_CLIENT_SECRET_HERE"
ru_name = "YOUR_RUNAME_HERE"
sandbox = true # Use sandbox (true) or production (false)

[sync]
# Time between automatic sync checks of searches and watchlists (in seconds)
poll_interval_seconds = 300

[sniper]
# Time in seconds before the auction close to place the bid
lead_time_seconds = 5
fallback_to_trading_api = true

[database]
# Path to SQLite database file
db_path = "ebay_watcher.db"

[deals]
# Threshold filter for the TUI deals view (price + shipping)
max_total_price = 100.0
```

---

## Getting Started

### 1. Build and Run Tests
Ensure everything compiles and the test suite passes:
```bash
cargo test
```

### 2. Start the Daemon
Run the background daemon. It will initialize the SQLite database (`ebay_watcher.db`) and run in a continuous sync loop:
```bash
cargo run -p ebay_watcher_daemon
```

### 3. Start the Terminal UI (TUI)
In a separate terminal tab/session, launch the TUI to view your dashboard:
```bash
cargo run -p ebay_watcher_tui
```

---

## TUI Keyboard Shortcuts

*   `Tab` / `Shift+Tab`: Switch tabs (Dashboard, Search Matches, Watchlist, Deals, Snipes).
*   `Up` / `Down` Arrow: Navigate item list.
*   `b`: Schedule a bid intent for the highlighted item.
*   `x` (in Snipes tab): Cancel a pending scheduled bid intent. This immediately updates the database and triggers a `SIGUSR1` signal to update the background daemon.
*   `q` / `Esc`: Quit the TUI application.

---

## Internal Mechanisms

### Bid Snipe Execution Delay
When a bid intent is set to `pending` in the database, the daemon's scheduler detects it and calculates the target runtime using:
$$\text{Execution Delay} = \text{Auction End Time} - \text{Lead Time} - \text{Current Time}$$
A non-blocking asynchronous tokio sleep task is spawned. When the timer expires, the daemon fetches the current authorization token, sets the status to `attempted`, dispatches the API proxy bid, and updates the database status to `succeeded` or `failed` based on the response.

### Transient Error Retries & Backoff
All outbound network operations are wrapped in an exponential backoff helper that checks `error.is_transient()`. Connection issues, timeouts, and HTTP status codes `429` (Rate Limited) or `5xx` (Server Error) will trigger a retry with exponential delays (doubling every try up to 3 retries). Permanent failures (e.g. invalid credentials or resource missing) fail fast without retrying.
