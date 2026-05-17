import typer
import asyncio
from .scheduler import start_scheduler, BID_CONFIGS
from .bot import AutoBidderBot

app = typer.Typer(help="Auto Bidder CLI for SwapAuction Wisc")

@app.command()
def start():
    """
    Starts the background scheduler daemon. 
    It will sync watched items periodically and trigger bids an exact number of seconds before ending.
    """
    typer.echo("Starting Auto Bidder Daemon...")
    try:
        asyncio.run(start_scheduler())
    except KeyboardInterrupt:
        typer.echo("Exited.")

@app.command()
def list_watched():
    """
    Manually check currently watched items and print them to the console.
    """
    typer.echo("Fetching watched items...")
    
    async def fetch():
        bot = AutoBidderBot()
        await bot.start()
        await bot.login()
        items = await bot.get_watched_items()
        await bot.close()
        return items

    items = asyncio.run(fetch())
    
    if not items:
        typer.echo("No watched items found.")
    else:
        for item in items:
            typer.echo(f"Item ID: {item.get('item_id')} | Ends: {item.get('end_time')} | Current Bid: {item.get('current_bid')}")

@app.command()
def set_max_bid(item_id: str, max_bid: float):
    """
    Configure the maximum bid amount for a given item ID.
    (Note: This currently only configures in memory for demonstration. 
     You would link this to a local JSON/SQLite in a production setup)
    """
    BID_CONFIGS[item_id] = {"max_bid": max_bid}
    typer.echo(f"Max bid for Item ID '{item_id}' set to ${max_bid:.2f}")

if __name__ == "__main__":
    app()
