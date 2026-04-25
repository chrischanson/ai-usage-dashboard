import os
from dotenv import load_dotenv

load_dotenv()

SWAP_USERNAME = os.getenv("SWAP_USERNAME")
SWAP_PASSWORD = os.getenv("SWAP_PASSWORD")
BID_SECONDS_BEFORE_END = int(os.getenv("BID_SECONDS_BEFORE_END", "5"))

if not SWAP_USERNAME or not SWAP_PASSWORD:
    print("Warning: SWAP_USERNAME or SWAP_PASSWORD not set in environment.")
