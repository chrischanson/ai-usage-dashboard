import asyncio
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from .bot import AutoBidderBot
from . import config

# Store scheduled job IDs so we don't duplicate
scheduled_jobs = set()

# Configuration store for bids
# In a real app, this should be backed by SQLite or JSON. We use a simple dictionary here.
# item_id -> {'max_bid': float}
BID_CONFIGS = {}

async def execute_bid(item_id: str, amount: float):
    print(f"[{datetime.datetime.now()}] Executing scheduled bid for Item '{item_id}' at ${amount}")
    bot = AutoBidderBot()
    await bot.start()
    try:
        await bot.login()
        await bot.place_bid(item_id, amount)
    except Exception as e:
        print(f"Error during scheduled bid execution for item {item_id}: {e}")
    finally:
        await bot.close()

async def sync_watched_items(scheduler: AsyncIOScheduler):
    print(f"[{datetime.datetime.now()}] Syncing watched items from Swap Auction...")
    bot = AutoBidderBot()
    await bot.start()
    
    try:
        await bot.login()
        items = await bot.get_watched_items()
    except Exception as e:
        print(f"Failed to fetch watched items: {e}")
        return
    finally:
        await bot.close()

    for item in items:
        item_id = item["item_id"]
        end_time = item["end_time"]
        
        # Calculate exactly when to bid
        bid_time = end_time - datetime.timedelta(seconds=config.BID_SECONDS_BEFORE_END)
        job_id = f"bid_{item_id}"

        # Should we bid? Is there a config?
        if job_id not in scheduled_jobs:
            if bid_time > datetime.datetime.now():
                # Let's say we just use current bid + 1 if no max bid is configured
                amount = BID_CONFIGS.get(item_id, {}).get("max_bid", float(item["current_bid"].replace('$', '').replace(',', '')) + 1.0)
                
                print(f"Scheduling bid for Item {item_id} at {bid_time} (Current Bid: {item['current_bid']})")
                scheduler.add_job(
                    execute_bid,
                    trigger=DateTrigger(run_date=bid_time),
                    args=[item_id, amount],
                    id=job_id,
                    replace_existing=True
                )
                scheduled_jobs.add(job_id)
            else:
                print(f"Item {item_id} has already ended or is too close to ending.")

# The main background service loop
async def start_scheduler():
    print("Starting Auto Bidder Background Service...")
    scheduler = AsyncIOScheduler()
    
    # Run sync every 30 minutes
    scheduler.add_job(sync_watched_items, "interval", minutes=30, args=[scheduler], id="sync_job")
    
    scheduler.start()
    
    # Run the first sync immediately
    await sync_watched_items(scheduler)
    
    try:
        # Keep the main thread alive
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down scheduler...")

if __name__ == "__main__":
    asyncio.run(start_scheduler())
