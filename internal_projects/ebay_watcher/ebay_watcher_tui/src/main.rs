use std::io::{self, Stdout};
use std::time::{Duration, Instant};
use std::path::Path;
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Tabs, Table, Row, Cell, Clear, Wrap},
    Frame, Terminal,
};
use chrono::{TimeZone, Utc};
pub mod ui;

use ebay_watcher_core::config::Config;
use ebay_watcher_core::db::{init_db, set_token};
use ebay_watcher_core::ebay::{EbayClient, RealEbayClient};
use ebay_watcher_core::models::{Item, BidIntent};
use crate::ui::{DashboardState, render_dashboard};

enum InputMode {
    Normal,
    BidModal {
        item_id: String,
        item_title: String,
        item_price: f64,
        end_time: i64,
        input: String,
        error: Option<String>,
    },
    AuthModal {
        input: String,
        error: Option<String>,
    },
}

struct App {
    active_tab: usize,
    db_path: String,
    config: Config,
    items: Vec<Item>,
    filtered_items: Vec<Item>,
    bid_intents: Vec<BidIntent>,
    dashboard_state: DashboardState,
    selected_idx: usize,
    input_mode: InputMode,
    status_msg: Option<(String, Instant)>,
}

impl App {
    fn new(config: Config) -> Self {
        let db_path = config.database.db_path.clone();
        let conn = init_db(&db_path).expect("Failed to open database");
        let dashboard_state = DashboardState::load(&conn);
        
        let mut app = Self {
            active_tab: 0,
            db_path,
            config,
            items: Vec::new(),
            filtered_items: Vec::new(),
            bid_intents: Vec::new(),
            dashboard_state,
            selected_idx: 0,
            input_mode: InputMode::Normal,
            status_msg: None,
        };
        app.refresh_data();
        app
    }

    fn refresh_data(&mut self) {
        if let Ok(conn) = ebay_watcher_core::db::open_conn(&self.db_path) {
            // Load dashboard state
            self.dashboard_state = DashboardState::load(&conn);

            // Load items
            if let Ok(items) = ebay_watcher_core::db::get_items(&conn) {
                self.items = items;
            }

            // Load bid intents
            if let Ok(intents) = ebay_watcher_core::db::get_bid_intents(&conn) {
                self.bid_intents = intents;
            }
        }
        self.update_filtered_items();
    }

    fn update_filtered_items(&mut self) {
        self.filtered_items = match self.active_tab {
            1 => self.items.clone(), // Search Matches
            2 => self.items.clone(), // Watchlist (simplified)
            3 => {
                let limit = self.config.deals.max_total_price;
                self.items.iter()
                    .filter(|i| i.current_price + i.shipping_cost <= limit)
                    .cloned()
                    .collect()
            }
            _ => Vec::new(),
        };
    }

    fn set_status(&mut self, msg: &str) {
        self.status_msg = Some((msg.to_string(), Instant::now()));
    }

    fn active_items(&self) -> &[Item] {
        &self.filtered_items
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Load config
    let config_path = "config.toml";
    let config = if Path::new(config_path).exists() {
        Config::load_from_file(config_path)?
    } else {
        // Fallback default config
        Config {
            ebay: ebay_watcher_core::config::EbayConfig {
                client_id: "dummy".into(),
                client_secret: "dummy".into(),
                ru_name: "dummy".into(),
                dev_name: "dummy".into(),
                sandbox: true,
            },
            sync: ebay_watcher_core::config::SyncConfig {
                poll_interval_seconds: 60,
            },
            sniper: ebay_watcher_core::config::SniperConfig {
                lead_time_seconds: 5,
                fallback_to_trading_api: true,
            },
            database: ebay_watcher_core::config::DatabaseConfig {
                db_path: "ebay_watcher.db".into(),
            },
            deals: ebay_watcher_core::config::DealsConfig {
                max_total_price: 100.0,
            },
        }
    };

    // Terminal setup
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let app = App::new(config);
    let res = run_app(&mut terminal, app);

    // Terminal teardown
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    terminal.show_cursor()?;

    if let Err(err) = res {
        println!("{:?}", err);
    }

    Ok(())
}

fn run_app(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    mut app: App,
) -> io::Result<()> {
    let tick_rate = Duration::from_millis(500);
    let mut last_tick = Instant::now();

    loop {
        // Refresh periodically
        if last_tick.elapsed() >= tick_rate {
            app.refresh_data();
            last_tick = Instant::now();
        }

        terminal.draw(|f| ui(f, &app))?;

        let timeout = tick_rate
            .checked_sub(last_tick.elapsed())
            .unwrap_or(Duration::from_secs(0));

        if event::poll(timeout)? {
            if let Event::Key(key) = event::read()? {
                let current_mode = std::mem::replace(&mut app.input_mode, InputMode::Normal);
                match current_mode {
                    InputMode::Normal => match key.code {
                        KeyCode::Char('q') => return Ok(()),
                        KeyCode::Tab => {
                            app.active_tab = (app.active_tab + 1) % 5;
                            app.selected_idx = 0;
                            app.update_filtered_items();
                        }
                        KeyCode::Up => {
                            if app.selected_idx > 0 {
                                app.selected_idx -= 1;
                            }
                        }
                        KeyCode::Down => {
                            let max_idx = match app.active_tab {
                                1 | 2 | 3 => app.active_items().len(),
                                4 => app.bid_intents.len(),
                                _ => 0,
                            };
                            if max_idx > 0 && app.selected_idx < max_idx - 1 {
                                app.selected_idx += 1;
                            }
                        }
                        KeyCode::Char('r') => {
                            // Attempt the signal directly to avoid a TOCTOU race between
                            // the `daemon_active` snapshot and the actual kill call.
                            if let Some(pid) = app.dashboard_state.daemon_pid {
                                match nix::sys::signal::kill(
                                    nix::unistd::Pid::from_raw(pid as i32),
                                    nix::sys::signal::Signal::SIGUSR1,
                                ) {
                                    Ok(()) => app.set_status("Triggered daemon immediate synchronization."),
                                    Err(nix::errno::Errno::ESRCH) => app.set_status("Daemon process not found (stale PID file?)."),
                                    Err(e) => app.set_status(&format!("Failed to signal daemon: {e}")),
                                }
                            } else {
                                app.set_status("Daemon is not running (no PID file).");
                            }
                            app.refresh_data();
                        }
                        KeyCode::Char('a') => {
                            app.input_mode = InputMode::AuthModal {
                                input: String::new(),
                                error: None,
                            };
                        }
                        KeyCode::Char('b') => {
                            let items = app.active_items();
                            if (app.active_tab == 1 || app.active_tab == 2 || app.active_tab == 3) && !items.is_empty() && app.selected_idx < items.len() {
                                let item = &items[app.selected_idx];
                                app.input_mode = InputMode::BidModal {
                                    item_id: item.id.clone(),
                                    item_title: item.title.clone(),
                                    item_price: item.current_price,
                                    end_time: item.end_time,
                                    input: String::new(),
                                    error: None,
                                };
                            }
                        }
                        KeyCode::Char('x') => {
                            if app.active_tab == 4 && !app.bid_intents.is_empty() && app.selected_idx < app.bid_intents.len() {
                                let intent = &app.bid_intents[app.selected_idx];
                                if intent.status == ebay_watcher_core::models::BidStatus::Pending {
                                    if let Some(intent_id) = intent.id {
                                        if let Ok(conn) = ebay_watcher_core::db::open_conn(&app.db_path) {
                                            if ebay_watcher_core::db::update_bid_intent_status(
                                                &conn,
                                                intent_id,
                                                ebay_watcher_core::models::BidStatus::Cancelled,
                                                Some("Cancelled by user"),
                                            ).is_ok() {
                                                if let Some(pid) = app.dashboard_state.daemon_pid {
                                                    let _ = nix::sys::signal::kill(
                                                        nix::unistd::Pid::from_raw(pid as i32),
                                                        nix::sys::signal::Signal::SIGUSR1,
                                                    );
                                                }
                                                app.set_status(&format!("Cancelled snipe for intent ID {}", intent_id));
                                            } else {
                                                app.set_status("Failed to cancel snipe in database.");
                                            }
                                        }
                                        app.refresh_data();
                                    }
                                } else {
                                    app.set_status("Only pending snipes can be cancelled.");
                                }
                            }
                        }
                        _ => {}
                    },
                    InputMode::BidModal { item_id, item_title, item_price, end_time, mut input, mut error } => {
                        let mut next_mode = Some(InputMode::BidModal { item_id: item_id.clone(), item_title: item_title.clone(), item_price, end_time, input: input.clone(), error: error.clone() });
                        match key.code {
                            KeyCode::Esc => {
                                next_mode = None; // Reset to Normal
                            }
                            KeyCode::Char(c) if c.is_digit(10) || c == '.' => {
                                input.push(c);
                                next_mode = Some(InputMode::BidModal { item_id, item_title, item_price, end_time, input, error });
                            }
                            KeyCode::Backspace => {
                                input.pop();
                                next_mode = Some(InputMode::BidModal { item_id, item_title, item_price, end_time, input, error });
                            }
                            KeyCode::Enter => {
                                if let Ok(bid) = input.parse::<f64>() {
                                    if bid <= item_price {
                                        error = Some("Bid must be greater than current price!".to_string());
                                        next_mode = Some(InputMode::BidModal { item_id, item_title, item_price, end_time, input, error });
                                    } else {
                                        // Save bid intent
                                        if let Ok(conn) = ebay_watcher_core::db::open_conn(&app.db_path) {
                                            let target_time = end_time; // Raw auction end time (double subtraction fix)
                                            let intent = BidIntent {
                                                id: None,
                                                item_id: item_id.clone(),
                                                max_bid: bid,
                                                target_time,
                                                status: ebay_watcher_core::models::BidStatus::Pending,
                                                error_message: None,
                                            };
                                            if ebay_watcher_core::db::save_bid_intent(&conn, &intent).is_ok() {
                                                if let Some(pid) = app.dashboard_state.daemon_pid {
                                                    // Best-effort signal; ESRCH is silently ignored if daemon has exited.
                                                    let _ = nix::sys::signal::kill(
                                                        nix::unistd::Pid::from_raw(pid as i32),
                                                        nix::sys::signal::Signal::SIGUSR1,
                                                    );
                                                }
                                                app.set_status(&format!("Scheduled snipe of ${:.2} on item {}", bid, item_id));
                                            } else {
                                                app.set_status("Failed to write snipe intent to database.");
                                            }
                                        }
                                        next_mode = None;
                                        app.refresh_data();
                                    }
                                } else {
                                    error = Some("Invalid price format!".to_string());
                                    next_mode = Some(InputMode::BidModal { item_id, item_title, item_price, end_time, input, error });
                                }
                            }
                            _ => {}
                        }
                        if let Some(m) = next_mode {
                            app.input_mode = m;
                        }
                    }
                    InputMode::AuthModal { mut input, mut error } => {
                        let mut next_mode = Some(InputMode::AuthModal { input: input.clone(), error: error.clone() });
                        match key.code {
                            KeyCode::Esc => {
                                next_mode = None;
                            }
                            KeyCode::Char(c) => {
                                input.push(c);
                                next_mode = Some(InputMode::AuthModal { input, error });
                            }
                            KeyCode::Backspace => {
                                input.pop();
                                next_mode = Some(InputMode::AuthModal { input, error });
                            }
                            KeyCode::Enter => {
                                if input.trim().is_empty() {
                                    error = Some("Code cannot be empty!".to_string());
                                    next_mode = Some(InputMode::AuthModal { input, error });
                                } else {
                                    let client = RealEbayClient::new(app.config.clone());
                                    let token_res = tokio::runtime::Handle::current().block_on(client.get_token(input.trim()));
                                    match token_res {
                                        Ok(token) => {
                                            if let Ok(conn) = ebay_watcher_core::db::open_conn(&app.db_path) {
                                                if set_token(&conn, &token).is_ok() {
                                                    app.set_status("Successfully authorized with eBay!");
                                                    if let Some(pid) = app.dashboard_state.daemon_pid {
                                                        // Best-effort signal; ESRCH is silently ignored if daemon has exited.
                                                        let _ = nix::sys::signal::kill(
                                                            nix::unistd::Pid::from_raw(pid as i32),
                                                            nix::sys::signal::Signal::SIGUSR1,
                                                        );
                                                    }
                                                } else {
                                                    app.set_status("Failed to save credentials to database.");
                                                }
                                            }
                                            next_mode = None;
                                            app.refresh_data();
                                        }
                                        Err(e) => {
                                            error = Some(format!("OAuth Error: {:?}", e));
                                            next_mode = Some(InputMode::AuthModal { input, error });
                                        }
                                    }
                                }
                            }
                            _ => {}
                        }
                        if let Some(m) = next_mode {
                            app.input_mode = m;
                        }
                    }
                }
            }
        }
    }
}

fn ui(f: &mut Frame, app: &App) {
    let main_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Header
            Constraint::Length(3), // Tabs
            Constraint::Min(0),    // Main Panel
            Constraint::Length(2), // Status bar
        ])
        .split(f.size());

    // 1. Render Header
    let daemon_status_text = if app.dashboard_state.daemon_active {
        Span::styled("● DAEMON ACTIVE", Style::default().fg(Color::Green).add_modifier(Modifier::BOLD))
    } else {
        Span::styled("○ DAEMON INACTIVE", Style::default().fg(Color::Red).add_modifier(Modifier::BOLD))
    };

    let title_line = Line::from(vec![
        Span::styled("eBay Watcher 🎯  ", Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
        Span::raw(" |  "),
        daemon_status_text,
    ]);

    let header_p = Paragraph::new(title_line)
        .block(Block::default().borders(Borders::BOTTOM).border_style(Style::default().fg(Color::DarkGray)));
    f.render_widget(header_p, main_chunks[0]);

    // 2. Render Tabs
    let tab_titles = vec!["Dashboard", "Search Matches", "Watchlist", "Deals", "Snipes / Bid Intents"];
    let tabs = Tabs::new(tab_titles)
        .select(app.active_tab)
        .block(Block::default().borders(Borders::BOTTOM).border_style(Style::default().fg(Color::DarkGray)))
        .style(Style::default().fg(Color::Gray))
        .highlight_style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD));
    f.render_widget(tabs, main_chunks[1]);

    // 3. Render Main view based on tab
    match app.active_tab {
        0 => {
            render_dashboard(f, main_chunks[2], &app.dashboard_state);
        }
        1 => {
            render_items_table(f, main_chunks[2], &app.active_items(), app.selected_idx, " Search Matches (Polled by Saved Searches) ");
        }
        2 => {
            render_items_table(f, main_chunks[2], &app.active_items(), app.selected_idx, " Active Watchlist Items ");
        }
        3 => {
            render_items_table(f, main_chunks[2], &app.active_items(), app.selected_idx, " Deals (Total Cost <= $100.00) ");
        }
        4 => {
            render_bids_table(f, main_chunks[2], &app.bid_intents, app.selected_idx);
        }
        _ => {}
    }

    // 4. Render Status bar / Footer
    let keys_span = Span::styled(
        " [Tab] Next Tab | [r] Sync Daemon | [a] Auth code | [b] Setup Snipe | [x] Cancel Snipe | [q] Quit ",
        Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)
    );

    let status_text = if let Some((msg, inst)) = &app.status_msg {
        if inst.elapsed() < Duration::from_secs(4) {
            Span::styled(format!(" Status: {} ", msg), Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD))
        } else {
            keys_span
        }
    } else {
        keys_span
    };

    let status_p = Paragraph::new(Line::from(status_text))
        .block(Block::default().borders(Borders::TOP).border_style(Style::default().fg(Color::DarkGray)));
    f.render_widget(status_p, main_chunks[3]);

    // 5. Render Modals
    match &app.input_mode {
        InputMode::Normal => {}
        InputMode::BidModal { item_id, item_title, item_price, end_time: _, input, error } => {
            let size = f.size();
            let popup_area = Rect {
                x: size.width / 4,
                y: size.height / 3,
                width: size.width / 2,
                height: 9,
            };

            let mut lines = vec![
                Line::from(vec![Span::raw("Item ID: "), Span::styled(item_id, Style::default().fg(Color::White))]),
                Line::from(vec![Span::raw("Title: "), Span::styled(format!("{:.45}", item_title), Style::default().fg(Color::White))]),
                Line::from(vec![Span::raw("Current Price: "), Span::styled(format!("${:.2}", item_price), Style::default().fg(Color::Green))]),
                Line::from(vec![Span::raw("Enter Max Bid: "), Span::styled(format!("${}", input), Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD))]),
            ];

            if let Some(err) = error {
                lines.push(Line::from(Span::styled(err, Style::default().fg(Color::Red).add_modifier(Modifier::BOLD))));
            } else {
                lines.push(Line::from(Span::styled("Press [Enter] to submit | [Esc] to cancel", Style::default().fg(Color::DarkGray))));
            }

            let block = Block::default()
                .title(" Setup Snipe Bid ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(Color::Yellow));
            let paragraph = Paragraph::new(lines)
                .block(block)
                .wrap(Wrap { trim: true });

            f.render_widget(Clear, popup_area);
            f.render_widget(paragraph, popup_area);
        }
        InputMode::AuthModal { input, error } => {
            let size = f.size();
            let popup_area = Rect {
                x: size.width / 6,
                y: size.height / 3,
                width: (size.width * 2) / 3,
                height: 8,
            };

            let mut lines = vec![
                Line::from(Span::styled("Paste authorization code from eBay auth flow:", Style::default().fg(Color::White))),
                Line::from(Span::styled(input, Style::default().fg(Color::Yellow))),
            ];

            if let Some(err) = error {
                lines.push(Line::from(Span::styled(err, Style::default().fg(Color::Red).add_modifier(Modifier::BOLD))));
            } else {
                lines.push(Line::from(Span::styled("Press [Enter] to exchange and save | [Esc] to cancel", Style::default().fg(Color::DarkGray))));
            }

            let block = Block::default()
                .title(" eBay Authorization Code ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(Color::Yellow));
            let paragraph = Paragraph::new(lines)
                .block(block)
                .wrap(Wrap { trim: true });

            f.render_widget(Clear, popup_area);
            f.render_widget(paragraph, popup_area);
        }
    }
}

fn render_items_table(f: &mut Frame, area: Rect, items: &[Item], selected_idx: usize, title: &str) {
    let header_cells = vec!["ID", "Title", "Current Price", "Shipping", "BIN Price", "End Time"]
        .into_iter()
        .map(|h| Cell::from(h).style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)));
    let header = Row::new(header_cells)
        .style(Style::default().bg(Color::Blue))
        .height(1);

    let rows: Vec<Row> = items.iter().enumerate().map(|(i, item)| {
        let style = if i == selected_idx {
            Style::default().bg(Color::DarkGray).fg(Color::White).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::White)
        };
        let end_time_str = Utc.timestamp_opt(item.end_time, 0)
            .single()
            .map(|dt| dt.format("%Y-%m-%d %H:%M:%S").to_string())
            .unwrap_or_else(|| "".to_string());
        
        let bin_str = item.buy_it_now_price.map(|p| format!("${:.2}", p)).unwrap_or_else(|| "N/A".to_string());

        let cells = vec![
            Cell::from(item.id.clone()),
            Cell::from(item.title.clone()),
            Cell::from(format!("${:.2}", item.current_price)),
            Cell::from(format!("${:.2}", item.shipping_cost)),
            Cell::from(bin_str),
            Cell::from(end_time_str),
        ];
        Row::new(cells).style(style).height(1)
    }).collect();

    let table = Table::new(rows, [
        Constraint::Percentage(15),
        Constraint::Percentage(45),
        Constraint::Percentage(10),
        Constraint::Percentage(10),
        Constraint::Percentage(10),
        Constraint::Percentage(10),
    ])
    .header(header)
    .block(Block::default().title(title).borders(Borders::ALL).border_style(Style::default().fg(Color::Cyan)))
    .highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    f.render_widget(table, area);
}

fn render_bids_table(f: &mut Frame, area: Rect, bids: &[BidIntent], selected_idx: usize) {
    let header_cells = vec!["ID", "Item ID", "Max Bid", "Target Time", "Status", "Error Message"]
        .into_iter()
        .map(|h| Cell::from(h).style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)));
    let header = Row::new(header_cells)
        .style(Style::default().bg(Color::Blue))
        .height(1);

    let rows: Vec<Row> = bids.iter().enumerate().map(|(i, bid)| {
        let style = if i == selected_idx {
            Style::default().bg(Color::DarkGray).fg(Color::White).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::White)
        };
        let target_time_str = Utc.timestamp_opt(bid.target_time, 0)
            .single()
            .map(|dt| dt.format("%Y-%m-%d %H:%M:%S").to_string())
            .unwrap_or_else(|| "".to_string());

        let status_color = match bid.status.as_str() {
            "succeeded" => Color::Green,
            "failed" => Color::Red,
            "missed" => Color::Yellow,
            "pending" => Color::Cyan,
            _ => Color::White,
        };
        let status_cell = Cell::from(bid.status.to_string()).style(Style::default().fg(status_color).add_modifier(Modifier::BOLD));

        let cells = vec![
            Cell::from(bid.id.map(|id| id.to_string()).unwrap_or_default()),
            Cell::from(bid.item_id.clone()),
            Cell::from(format!("${:.2}", bid.max_bid)),
            Cell::from(target_time_str),
            status_cell,
            Cell::from(bid.error_message.clone().unwrap_or_default()),
        ];
        Row::new(cells).style(style).height(1)
    }).collect();

    let table = Table::new(rows, [
        Constraint::Percentage(8),
        Constraint::Percentage(15),
        Constraint::Percentage(12),
        Constraint::Percentage(20),
        Constraint::Percentage(15),
        Constraint::Percentage(30),
    ])
    .header(header)
    .block(Block::default().title(" Scheduled Bid Snipes ").borders(Borders::ALL).border_style(Style::default().fg(Color::Cyan)))
    .highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    f.render_widget(table, area);
}

#[cfg(test)]
mod tests {
    use super::*;
    use ebay_watcher_core::db::save_item;

    #[test]
    fn test_tui_app_filtering_deals() {
        let temp_db_path = "test_tui_deals.db";
        let _ = std::fs::remove_file(temp_db_path);

        let config = Config {
            ebay: ebay_watcher_core::config::EbayConfig {
                client_id: "dummy".into(),
                client_secret: "dummy".into(),
                ru_name: "dummy".into(),
                dev_name: "dummy".into(),
                sandbox: true,
            },
            sync: ebay_watcher_core::config::SyncConfig {
                poll_interval_seconds: 60,
            },
            sniper: ebay_watcher_core::config::SniperConfig {
                lead_time_seconds: 5,
                fallback_to_trading_api: true,
            },
            database: ebay_watcher_core::config::DatabaseConfig {
                db_path: temp_db_path.to_string(),
            },
            deals: ebay_watcher_core::config::DealsConfig {
                max_total_price: 100.0,
            },
        };

        let mut app = App::new(config);
        
        let conn = ebay_watcher_core::db::open_conn(temp_db_path).unwrap();
        
        // Save items: one cheap (under 100 total), one expensive (over 100 total)
        let cheap_item = Item {
            id: "cheap1".to_string(),
            title: "Cheap Item".to_string(),
            current_price: 80.0,
            shipping_cost: 15.0, // total 95.0
            buy_it_now_price: None,
            end_time: 12345,
        };
        let expensive_item = Item {
            id: "expensive1".to_string(),
            title: "Expensive Item".to_string(),
            current_price: 90.0,
            shipping_cost: 15.0, // total 105.0
            buy_it_now_price: None,
            end_time: 12345,
        };
        save_item(&conn, &cheap_item).unwrap();
        save_item(&conn, &expensive_item).unwrap();
        
        std::mem::drop(conn);

        // Refresh data to fetch from DB
        app.refresh_data();

        // 1. Tab 1 (Search Matches) should show both items
        app.active_tab = 1;
        app.update_filtered_items();
        assert_eq!(app.filtered_items.len(), 2);
        assert!(app.filtered_items.iter().any(|i| i.id == "cheap1"));
        assert!(app.filtered_items.iter().any(|i| i.id == "expensive1"));

        // 2. Tab 3 (Deals) should show only the cheap item (total <= 100)
        app.active_tab = 3;
        app.update_filtered_items();
        assert_eq!(app.filtered_items.len(), 1);
        assert_eq!(app.filtered_items[0].id, "cheap1");

        let _ = std::fs::remove_file(temp_db_path);
    }
}

