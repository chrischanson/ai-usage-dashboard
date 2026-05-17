# Auto Bidder

A Python background service and CLI to automatically bid on items from `swapauction.wisc.edu` a few seconds before the auction ends.

## Setup

1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
3. Set your environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your username and password
   ```

## Usage

This tool comes with a Typer CLI. 

To list watches:
```bash
python -m src.cli list-watched
```

To run the background bidding daemon that checks your watched items every 30 minutes and schedules bids:
```bash
python -m src.cli start
```
