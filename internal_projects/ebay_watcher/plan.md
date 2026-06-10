# eBay Watcher TUI Implementation Plan

> **For Antigravity:** Use `/home/dev/workspace/main/skills/superpowers/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Build a robust Rust-based eBay saved search monitor and automated bidding sniper consisting of a background daemon and a separate TUI client.

**Architecture:** Split-process model where a headless daemon handles eBay API syncing, OAuth refreshing, and exact-time snipe bidding, communicating via a shared SQLite database (WAL mode) with an interactive crossterm/ratatui TUI client. The TUI client sends SIGUSR1 signals to notify the daemon of immediate action requests.

**Tech Stack:** Rust (workspace), `ratatui` + `crossterm` (TUI), `tokio` (async runtime), `reqwest` (HTTP), `rusqlite` (SQLite), `serde` / `quick-xml` (serialization), `clap` (CLI arguments).

---

## Task 1: Cargo Workspace & Configuration Setup

**Files:**
- Create: `internal_projects/ebay_watcher/Cargo.toml`
- Create: `internal_projects/ebay_watcher/ebay_watcher_core/Cargo.toml`
- Create: `internal_projects/ebay_watcher/ebay_watcher_core/src/lib.rs`
- Create: `internal_projects/ebay_watcher/ebay_watcher_core/src/config.rs`
- Create: `internal_projects/ebay_watcher/config.example.toml`

**Step 1: Initialize the Cargo Workspace and Shared Library**
Create the workspace `Cargo.toml` specifying `ebay_watcher_core` as a member. Initialize `ebay_watcher_core` as a library crate. Define error types and configuration models mapping `config.example.toml` keys (App credentials, RuName, polling interval, snipe lead-time offset) using `serde`.

**Step 2: Write tests for Configuration Loading**
Implement a test in `ebay_watcher_core/src/config.rs` to verify that a sample TOML string parses correctly into configuration structs, including checking defaults for polling intervals and snipe lead-time offset.

**Step 3: Verify the configuration test passes**
Run: `cargo test -p ebay_watcher_core`
Expected: PASS

**Step 4: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(core): initialize workspace and configuration loading"
```

---

## Task 2: Database Schema & Migrations

**Files:**
- Modify: `internal_projects/ebay_watcher/ebay_watcher_core/Cargo.toml`
- Create: `internal_projects/ebay_watcher/ebay_watcher_core/src/db.rs`
- Create: `internal_projects/ebay_watcher/migrations/001_initial.sql`

**Step 1: Write SQL Migrations**
Define the database schema:
* `tokens`: `access_token` (TEXT), `refresh_token` (TEXT), `expires_at` (INTEGER)
* `items`: `id` (TEXT PRIMARY KEY), `title` (TEXT), `current_price` (REAL), `shipping_cost` (REAL), `buy_it_now_price` (REAL), `end_time` (INTEGER)
* `alerts`: `id` (INTEGER PRIMARY KEY), `item_id` (TEXT), `is_read` (INTEGER), `discovered_at` (INTEGER)
* `bid_intents`: `id` (INTEGER PRIMARY KEY), `item_id` (TEXT), `max_bid` (REAL), `target_time` (INTEGER), `status` (TEXT)

**Step 2: Implement Database Connection & WAL Setup**
In `db.rs`, implement `fn init_db(path: &str) -> Result<Connection>`. Ensure connection flags enable Write-Ahead Logging (`PRAGMA journal_mode=WAL;`), sets synchronous to normal (`PRAGMA synchronous=NORMAL;`), and sets `busy_timeout` to 5000ms. Apply SQL migrations.

**Step 3: Write tests for database operations**
Write unit tests verifying database migration success on `:memory:`, inserting and retrieving token rows, and inserting/updating `bid_intents`.

**Step 4: Verify database tests pass**
Run: `cargo test -p ebay_watcher_core db::tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(core): add SQLite database schema and connection initialization"
```

---

## Task 3: Mockable eBay Client

**Files:**
- Create: `internal_projects/ebay_watcher/ebay_watcher_core/src/ebay/mod.rs`
- Create: `internal_projects/ebay_watcher/ebay_watcher_core/src/ebay/client.rs`

**Step 1: Define the EbayClient Trait**
Create a trait containing:
* `async fn get_token(&self, code: &str) -> Result<OAuthToken>`
* `async fn refresh_token(&self, refresh_token: &str) -> Result<OAuthToken>`
* `async fn fetch_mye_bay_buying(&self, token: &str) -> Result<MyeBayBuyingData>`
* `async fn search_items(&self, token: &str, query: &str) -> Result<Vec<ItemSummary>>`
* `async fn place_bid(&self, token: &str, item_id: &str, amount: f64) -> Result<BidResult>`

**Step 2: Implement MockEbayClient**
Create a test-only `MockEbayClient` struct implementing the trait to return deterministic mocked data without hitting the network.

**Step 3: Write tests for Client Serialization**
Write tests validating the parsing of eBay Trading API XML responses and REST JSON search response payloads using test data.

**Step 4: Verify serialization tests pass**
Run: `cargo test -p ebay_watcher_core ebay::client::tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(core): implement mockable eBay Client and serialization tests"
```

---

## Task 4: Daemon Synchronization Engine

**Files:**
- Create: `internal_projects/ebay_watcher/ebay_watcher_daemon/Cargo.toml`
- Create: `internal_projects/ebay_watcher/ebay_watcher_daemon/src/main.rs`
- Create: `internal_projects/ebay_watcher/ebay_watcher_daemon/src/sync.rs`

**Step 1: Initialize Daemon Binary**
Initialize `ebay_watcher_daemon` in the workspace. Add dependencies to `ebay_watcher_core` and `tokio`.

**Step 2: Implement Polling Logic with Exponential Backoff**
In `sync.rs`, build the sync engine. It reads the user's saved searches and watchlist from SQLite, queries the eBay API, matches against existing item IDs in SQLite, marks differences as `[NEW]` inside the `alerts` table, and commits updates. Implement exponential backoff on HTTP 429/5xx responses.

**Step 3: Write tests for Synchronization Logic**
Write a test that registers a saved search in a mock SQLite database, mocks the search results containing 1 new item, triggers a sync run, and asserts that a row is successfully added to the `alerts` table.

**Step 4: Run sync engine tests**
Run: `cargo test -p ebay_watcher_daemon sync::tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(daemon): implement synchronization engine and polling tests"
```

---

## Task 5: Snipe Scheduler & Crash Recovery

**Files:**
- Create: `internal_projects/ebay_watcher/ebay_watcher_daemon/src/scheduler.rs`
- Modify: `internal_projects/ebay_watcher/ebay_watcher_daemon/src/main.rs`

**Step 1: Implement Startup Crash Recovery**
In `scheduler.rs`, implement startup recovery: check the DB for pending or attempted bids whose target execution times have already passed. Update those status fields to `missed` or `failed` (e.g. "Crashed during execution").

**Step 2: Implement the Bidding Scheduler**
Build the sniping loop. It fetches active `pending` bids from SQLite, calculates their execution delays, and spawns `tokio::time::sleep_until` jobs. When triggered, it executes `place_bid` via the client and updates the status (`succeeded` / `failed`).

**Step 3: Write tests for Snipe Execution and Recovery**
Write tests verifying that expired bids are correctly marked as `missed` on startup, and that upcoming bids fire at the correct relative time when mock-scheduled.

**Step 4: Run scheduler tests**
Run: `cargo test -p ebay_watcher_daemon scheduler::tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(daemon): implement snipe scheduler and crash recovery engine"
```

---

## Task 6: POSIX Signal Sync Trigger

**Files:**
- Modify: `internal_projects/ebay_watcher/ebay_watcher_daemon/src/main.rs`

**Step 1: Implement SIGUSR1 Handling**
Using `tokio::signal::unix`, set up a listener in the daemon's main loop for the `SIGUSR1` signal. When received, it interrupts the sync loop's sleeping interval to trigger an immediate, forced database reload and API synchronization check.

**Step 2: Write tests for Signal Triggering**
Write an integration test that starts the daemon, triggers a signal mock-send, and asserts that the polling process initiates immediately instead of waiting for the timer.

**Step 3: Run signal handling tests**
Run: `cargo test -p ebay_watcher_daemon main::tests`
Expected: PASS

**Step 4: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(daemon): add signal handling for forced TUI-driven refreshes"
```

---

## Task 7: TUI Client Shell & Dashboard

**Files:**
- Create: `internal_projects/ebay_watcher/ebay_watcher_tui/Cargo.toml`
- Create: `internal_projects/ebay_watcher/ebay_watcher_tui/src/main.rs`
- Create: `internal_projects/ebay_watcher/ebay_watcher_tui/src/ui.rs`

**Step 1: Setup TUI Shell with Ratatui**
Create the client crate `ebay_watcher_tui`. Implement terminal initialization (raw mode, alternative screen) using `crossterm`. Set up a layout containing Header, Main View (defaulting to Dashboard), and a Footer for status logs.

**Step 2: Draw the Dashboard View**
Build the Dashboard view listing overall daemon status, SQLite DB health, active bid intents, and recent system alerts fetched from the database.

**Step 3: Write tests for TUI rendering**
Write unit tests with a mock terminal buffer (`ratatui::backend::TestBackend`) to verify that the header, footer, and active view block borders render correctly.

**Step 4: Run TUI rendering tests**
Run: `cargo test -p ebay_watcher_tui ui::tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(tui): bootstrap ratatui shell and draw dashboard view"
```

---

## Task 8: View Controller & Navigation

**Files:**
- Create: `internal_projects/ebay_watcher/ebay_watcher_tui/src/controller.rs`
- Modify: `internal_projects/ebay_watcher/ebay_watcher_tui/src/ui.rs`

**Step 1: Implement Keyboard Controls & Tab Switching**
In `controller.rs`, handle keystrokes: `Tab` keys cycle views (Dashboard, Saved Searches, Watchlist, Deals, Alert Feed). Implement list scrolling (Up/Down arrow keys or `j`/`k`).

**Step 2: Connect TUI Refresh key to Daemon**
Implement the `r` key logic. When pressed, the TUI retrieves the daemon's PID from a local pidfile, sends `SIGUSR1`, and re-reads the database.

**Step 3: Write tests for View Switching**
Write unit tests validating that keypresses correctly update the application state machine's active tab index and scroll offsets.

**Step 4: Run controller tests**
Run: `cargo test -p ebay_watcher_tui controller::tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(tui): implement keyboard navigation and signal triggering logic"
```

---

## Task 9: Search Matches, Watchlist, and Deals Views

**Files:**
- Modify: `internal_projects/ebay_watcher/ebay_watcher_tui/src/ui.rs`

**Step 1: Draw Item Lists & Indicators**
Implement the rendering of search results and watchlist items. Render inline `[NEW]` markers for items whose IDs match unread alerts, and `[DEAL]` markers for items matching configured budget/condition criteria.

**Step 2: Add Watchlist Actions**
Implement the `w` keystroke. When selected in search lists, insert the item ID into the SQLite `watch_list` table and queue a watch operation for the daemon.

**Step 3: Write tests for Indicators rendering**
Write tests ensuring that items marked as new or deals render with appropriate stylized text modifications in the terminal mock buffer.

**Step 4: Run UI list rendering tests**
Run: `cargo test -p ebay_watcher_tui ui::list_tests`
Expected: PASS

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(tui): implement items rendering, new/deal indicators, and watchlist actions"
```

---

## Task 10: Bid Intent Interface

**Files:**
- Modify: `internal_projects/ebay_watcher/ebay_watcher_tui/src/ui.rs`
- Modify: `internal_projects/ebay_watcher/ebay_watcher_tui/src/controller.rs`

**Step 1: Implement the Snipe Scheduling Form**
Implement the `b` keystroke action. It opens a modal dialog allowing the user to enter a max bid amount. Upon confirmation, it inserts a new `pending` row into the `bid_intents` table and triggers a daemon signal.

**Step 2: Draw the Bids Log View**
Add the Bid Intents view listing scheduled, completed, and missed snipes. Implement the `x` keystroke to mark a `pending` snipe as `cancelled`.

**Step 3: Write tests for Scheduling Form**
Write unit tests simulating form entry, validating value inputs, and verifying that the database transaction registers correctly on submission.

**Step 4: Run final integration test suite**
Run: `cargo test`
Expected: PASS (All test targets across workspace)

**Step 5: Commit**
```bash
git add internal_projects/ebay_watcher/
git commit -m "feat(tui): implement bidding form interface and cancel actions"
```

---

## Execution Handoff

Plan complete and saved to `internal_projects/ebay_watcher/plan.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagents per task, review between tasks, and perform fast iteration.

**2. Parallel Session (separate)** - Open a new session with the `executing-plans` skill to process the tasks batch-by-batch with checkpointing.

**Which approach?**
