use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Wrap},
    Frame,
};
use chrono::{TimeZone, Utc};
use std::fs;
use std::path::Path;
use ebay_watcher_core::models::{Item, Alert, OAuthToken};

pub struct DashboardState {
    pub daemon_pid: Option<i32>,
    pub daemon_active: bool,
    pub oauth_token: Option<OAuthToken>,
    pub total_items: usize,
    pub unread_alerts: usize,
    pub active_snipes: usize,
    pub recent_alerts: Vec<(Alert, Item)>,
}

impl DashboardState {
    pub fn load(conn: &rusqlite::Connection) -> Self {
        // Read daemon pid
        let pid_file = "ebay_watcher.pid";
        let mut daemon_pid = None;
        let mut daemon_active = false;
        if Path::new(pid_file).exists() {
            if let Ok(pid_str) = fs::read_to_string(pid_file) {
                if let Ok(pid) = pid_str.trim().parse::<i32>() {
                    daemon_pid = Some(pid);
                    // Check if process is alive (using kill 0)
                    daemon_active = unsafe { libc::kill(pid, 0) == 0 };
                }
            }
        }

        // Get oauth status
        let oauth_token = ebay_watcher_core::db::get_token(conn).ok().flatten();

        // Get stats
        let total_items = match conn.query_row("SELECT COUNT(*) FROM items", [], |r| r.get::<_, usize>(0)) {
            Ok(c) => c,
            _ => 0,
        };

        let unread_alerts = match conn.query_row("SELECT COUNT(*) FROM alerts WHERE is_read = 0", [], |r| r.get::<_, usize>(0)) {
            Ok(c) => c,
            _ => 0,
        };

        let active_snipes = match conn.query_row("SELECT COUNT(*) FROM bid_intents WHERE status = 'pending'", [], |r| r.get::<_, usize>(0)) {
            Ok(c) => c,
            _ => 0,
        };

        // Get recent alerts
        let mut recent_alerts = Vec::new();
        if let Ok(mut stmt) = conn.prepare(
            "SELECT a.id, a.item_id, a.is_read, a.discovered_at,
                    i.title, i.current_price, i.shipping_cost, i.buy_it_now_price, i.end_time
             FROM alerts a
             JOIN items i ON a.item_id = i.id
             ORDER BY a.discovered_at DESC LIMIT 5"
        ) {
            if let Ok(rows) = stmt.query_map([], |row| {
                Ok((
                    Alert {
                        id: row.get(0)?,
                        item_id: row.get(1)?,
                        is_read: row.get::<_, i32>(2)? != 0,
                        discovered_at: row.get(3)?,
                    },
                    Item {
                        id: row.get(1)?,
                        title: row.get(4)?,
                        current_price: row.get(5)?,
                        shipping_cost: row.get(6)?,
                        buy_it_now_price: row.get(7)?,
                        end_time: row.get(8)?,
                    }
                ))
            }) {
                for r in rows {
                    if let Ok(val) = r {
                        recent_alerts.push(val);
                    }
                }
            }
        }

        Self {
            daemon_pid,
            daemon_active,
            oauth_token,
            total_items,
            unread_alerts,
            active_snipes,
            recent_alerts,
        }
    }
}

pub fn render_dashboard(f: &mut Frame, area: Rect, state: &DashboardState) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(area);

    let left_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(8), // System Status
            Constraint::Length(8), // Stats
            Constraint::Min(0),
        ])
        .split(chunks[0]);

    // Panel 1: System Status
    let daemon_status_span = if state.daemon_active {
        Span::styled(
            format!("ACTIVE (PID {})", state.daemon_pid.unwrap_or(0)),
            Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
        )
    } else {
        Span::styled(
            "INACTIVE",
            Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
        )
    };

    let oauth_status_span = if let Some(ref t) = state.oauth_token {
        if Utc::now().timestamp() >= t.expires_at {
            Span::styled("EXPIRED", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD))
        } else {
            let expires_in = t.expires_at - Utc::now().timestamp();
            Span::styled(
                format!("AUTHORIZED (expires in {}m)", expires_in / 60),
                Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
            )
        }
    } else {
        Span::styled("NOT AUTHORIZED", Style::default().fg(Color::Red).add_modifier(Modifier::BOLD))
    };

    let status_text = vec![
        Line::from(vec![Span::raw("Daemon Status: "), daemon_status_span]),
        Line::from(vec![Span::raw("OAuth Session: "), oauth_status_span]),
        Line::from(vec![
            Span::raw("Auth Instructions: "),
            Span::styled(
                "Press [a] to paste authorization code",
                Style::default().fg(Color::DarkGray).add_modifier(Modifier::ITALIC),
            ),
        ]),
    ];

    let status_paragraph = Paragraph::new(status_text)
        .block(Block::default().title(" System Status ").borders(Borders::ALL).border_style(Style::default().fg(Color::Cyan)))
        .wrap(Wrap { trim: true });
    f.render_widget(status_paragraph, left_chunks[0]);

    // Panel 2: Quick Stats
    let stats_text = vec![
        Line::from(vec![
            Span::raw("Total Synced Items: "),
            Span::styled(state.total_items.to_string(), Style::default().fg(Color::White).add_modifier(Modifier::BOLD)),
        ]),
        Line::from(vec![
            Span::raw("Unread Deal Alerts: "),
            Span::styled(state.unread_alerts.to_string(), Style::default().fg(Color::LightRed).add_modifier(Modifier::BOLD)),
        ]),
        Line::from(vec![
            Span::raw("Active Snipes Scheduled: "),
            Span::styled(state.active_snipes.to_string(), Style::default().fg(Color::LightYellow).add_modifier(Modifier::BOLD)),
        ]),
    ];

    let stats_paragraph = Paragraph::new(stats_text)
        .block(Block::default().title(" Statistics ").borders(Borders::ALL).border_style(Style::default().fg(Color::Cyan)))
        .wrap(Wrap { trim: true });
    f.render_widget(stats_paragraph, left_chunks[1]);

    // Panel 3: Recent Alerts
    let mut alert_lines = Vec::new();
    if state.recent_alerts.is_empty() {
        alert_lines.push(Line::from(Span::styled(
            "No alerts found. Daemon is syncing in the background...",
            Style::default().fg(Color::DarkGray).add_modifier(Modifier::ITALIC),
        )));
    } else {
        for (alert, item) in &state.recent_alerts {
            let time_str = Utc.timestamp_opt(alert.discovered_at, 0)
                .single()
                .map(|dt| dt.format("%H:%M:%S").to_string())
                .unwrap_or_else(|| "".to_string());
            alert_lines.push(Line::from(vec![
                Span::styled(format!("[{}] ", time_str), Style::default().fg(Color::DarkGray)),
                Span::styled(format!("{:.35} ", item.title), Style::default().fg(Color::White)),
                Span::styled(format!("${:.2} ", item.current_price), Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)),
            ]));
        }
    }

    let alerts_paragraph = Paragraph::new(alert_lines)
        .block(Block::default().title(" Recent Alerts ").borders(Borders::ALL).border_style(Style::default().fg(Color::Yellow)))
        .wrap(Wrap { trim: true });
    f.render_widget(alerts_paragraph, chunks[1]);
}
