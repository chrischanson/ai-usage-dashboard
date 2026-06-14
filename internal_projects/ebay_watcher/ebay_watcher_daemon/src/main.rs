pub mod sync;
pub mod scheduler;

use std::fs;
use std::path::Path;
use std::process;
use std::time::Duration;
use tokio::signal::unix::{signal, SignalKind};
use ebay_watcher_core::config::Config;
use ebay_watcher_core::db::init_db;
use ebay_watcher_core::ebay::{EbayClient, RealEbayClient};
use crate::sync::SyncEngine;
use crate::scheduler::SnipeScheduler;

#[tokio::main]
async fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    let config_path = "config.toml";
    let config = if Path::new(config_path).exists() {
        Config::load_from_file(config_path)?
    } else {
        println!("config.toml not found. Please create one based on config.example.toml.");
        process::exit(1);
    };
    let client = RealEbayClient::new(config.clone());
    run_daemon(config, client).await
}

pub async fn run_daemon<C: EbayClient + Clone + 'static>(
    config: Config,
    client: C,
) -> std::result::Result<(), Box<dyn std::error::Error>> {
    // 1. Setup signal listeners immediately to avoid race conditions
    let mut sigusr1 = signal(SignalKind::user_defined1())?;
    let mut sigint = signal(SignalKind::interrupt())?;
    let mut sigterm = signal(SignalKind::terminate())?;

    // 2. Initialize DB
    let conn = init_db(&config.database.db_path)?;

    // 4. Write PID file atomically: write to a temp path then rename into place
    //    so the TUI never reads a partially-written or empty file.
    let pid = process::id();
    let pid_file = "ebay_watcher.pid";
    let pid_tmp = format!("{}.tmp", pid_file);
    fs::write(&pid_tmp, pid.to_string())?;
    fs::rename(&pid_tmp, pid_file)?;
    println!("Daemon started with PID {}", pid);

    // 5. Initialize sync engine, and scheduler
    let sync_engine = SyncEngine::new(client.clone());
    let scheduler = SnipeScheduler::new(
        client,
        config.sniper.lead_time_seconds,
        config.database.db_path.clone(),
    );

    // 6. Run startup recovery
    if let Err(e) = scheduler.recover_and_cleanup(&conn) {
        println!("Error during startup recovery: {:?}", e);
    }

    // 7. First sync and schedule
    if let Err(e) = sync_engine.run_sync_cycle(&config.database.db_path).await {
        println!("Error during initial sync: {:?}", e);
    }
    if let Err(e) = scheduler.schedule_upcoming_bids(&conn) {
        println!("Error during initial scheduling: {:?}", e);
    }

    let poll_interval = Duration::from_secs(config.sync.poll_interval_seconds);

    println!("Entering daemon loop. Polling every {} seconds.", config.sync.poll_interval_seconds);

    loop {
        tokio::select! {
            _ = tokio::time::sleep(poll_interval) => {
                println!("Interval timer triggered sync.");
                let _ = sync_engine.run_sync_cycle(&config.database.db_path).await;
                let _ = scheduler.schedule_upcoming_bids(&conn);
            }
            _ = sigusr1.recv() => {
                println!("SIGUSR1 signal triggered immediate sync.");
                let _ = sync_engine.run_sync_cycle(&config.database.db_path).await;
                let _ = scheduler.schedule_upcoming_bids(&conn);
            }
            _ = sigint.recv() => {
                println!("SIGINT received. Shutting down daemon...");
                break;
            }
            _ = sigterm.recv() => {
                println!("SIGTERM received. Shutting down daemon...");
                break;
            }
        }
    }

    // Clean up PID file
    let _ = fs::remove_file(pid_file);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use nix::sys::signal::{self as nix_signal, Signal};
    use nix::unistd::Pid;
    use tokio::time::sleep;
    use ebay_watcher_core::ebay::MockEbayClient;

    #[tokio::test]
    async fn test_sigusr1_trigger() {
        // Create dummy config.toml for daemon main initialization during tests
        let config_toml = r#"
            [ebay]
            client_id = "test-id"
            client_secret = "test-secret"
            ru_name = "test-runame"

            [sync]
            poll_interval_seconds = 3600

            [sniper]
            lead_time_seconds = 5

            [database]
            db_path = "test_main.db"
        "#;
        fs::write("test_config.toml", config_toml).unwrap();

        // Clean up any stale PID file
        let _ = fs::remove_file("ebay_watcher.pid");

        let mock_client = MockEbayClient::new();

        // Spawn daemon in background task calling run_daemon
        let handle = tokio::spawn(async move {
            let config = Config::load_from_file("test_config.toml").unwrap();
            if let Err(e) = run_daemon(config, mock_client).await {
                println!("Daemon run failed: {:?}", e);
            }
        });

        // Wait for PID file to be written
        let pid_file = "ebay_watcher.pid";
        let mut attempts = 0;
        while !Path::new(pid_file).exists() && attempts < 20 {
            sleep(Duration::from_millis(100)).await;
            attempts += 1;
        }

        assert!(Path::new(pid_file).exists());

        let pid_str = fs::read_to_string(pid_file).unwrap();
        let pid = pid_str.parse::<i32>().unwrap();

        // Let the daemon finish its startup sync cycle
        sleep(Duration::from_millis(200)).await;

        // Send SIGUSR1 to daemon
        nix_signal::kill(Pid::from_raw(pid), Signal::SIGUSR1).unwrap();

        // Let the signal register and process
        sleep(Duration::from_millis(200)).await;

        // Send SIGINT to shut down
        nix_signal::kill(Pid::from_raw(pid), Signal::SIGINT).unwrap();

        // Wait for shutdown and cleanup
        let _ = handle.await;

        let mut attempts = 0;
        while Path::new(pid_file).exists() && attempts < 20 {
            sleep(Duration::from_millis(100)).await;
            attempts += 1;
        }

        assert!(!Path::new(pid_file).exists());
        
        let _ = fs::remove_file("test_config.toml");
        let _ = fs::remove_file("test_main.db");
    }
}
