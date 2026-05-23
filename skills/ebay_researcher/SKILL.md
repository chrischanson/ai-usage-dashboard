---
name: "eBay Product Researcher"
description: "Audits an eBay listing, scans for warning flags, researches recent sold prices, and suggests a target deal price at a 30% discount."
default_agent: "agy"
required_vars:
  - EBAY_URL
---

# Instructions

> **⚠️ Note:** eBay typically blocks automated page fetches (HTTP 403). This skill includes fallback strategies using web search, aggregation sites (WatchCharts, EveryWatch, Chrono24), and search-engine snippets to recover listing details. If the primary fetch fails, proceed with the fallback steps — do not treat a 403 as a dead end.

You are an expert product researcher and bargain hunter. Your task is to perform thorough research on a target eBay listing and generate a structured value report.

**Output convention:** Place all generated files inside the `{OUTPUT_DIR}` directory. This keeps each run's output self-contained under `skills/runs/`.

## Input Target Listing
* **Target URL:** {EBAY_URL}

## Research Steps to Execute

### 1. Retrieve and Parse Listing Details
* **Primary:** Use your browsing/fetch tool to load the target eBay URL `{EBAY_URL}`.
* **Fallback (if eBay returns 403 Forbidden):** eBay blocks automated page fetches. When this happens, use these alternative approaches to recover the data:

  **Approach A — Web search the item number:** Search the web for the exact item ID (the number in the URL) plus "ebay". Search snippets often reveal the full listing title, including the critical model/reference number.

  **Approach B — Fetch the eBay category browse page (`/b/`):** This endpoint is **not blocked** and returns listing results with prices, shipping, bid counts, and item condition. Build the URL like this:
  ```
  https://www.ebay.com/b/Jewelry-Watches/31387/bn_7119185158?_nkw={MODEL_NUMBER}&LH_Sold=1&LH_Complete=1&rt=nc
  ```
  For watches, always use category **31387** (Watches, Parts & Accessories). Remove `LH_Sold=1&LH_Complete=1` to see active listings.  
  *Note: The response contains obfuscated text interspersed with real data — extract prices (look for `$` followed by numbers), bid counts (`# bids`), and listing titles. Use grep-like scanning.*

  **Approach C — Fetch the product page (`/p/`):** Some items have an eBay Product ID (ePID). If you can find the ePID (via web search or aggregation sites), the product page at `https://www.ebay.com/p/{ePID}` returns full item specifications, condition, and pricing.

  **Approach D — Third-party aggregation sites:** Look up the item on:
  - **WatchCharts Marketplace** (marketplace.watchcharts.com) — search by model number or eBay item ID. Shows sold prices, seller feedback, condition, and full specs.
  - **EveryWatch** (everywatch.com) — indexes eBay sold listings with prices, dates, and condition.
  - **Chrono24** (chrono24.com) — search by reference number for current asking/completed prices.

  **Approach E — Extract the model number** from the full listing title (found via Approach A or B). This is critical for finding comparable prices. In watches, the reference number (e.g., SBGA203, SBGX261) is the key identifier.

* Extract and document the following item details:
  * Brand and exact model name.
  * Reference number or model number (critical for watches and electronics).
  * Current listing price (and shipping cost).
  * **Sale format:** Auction (with starting bid / reserve) or Buy It Now (fixed price).
  * Listed condition (e.g., Brand New, Pre-owned, Parts/Not Working).
  * Seller feedback rating and score.

### 2. Perform Red Flag Audit (Condition & Risk Assessment)
* Scan the listing title, specifications, and the **entire description** for potential defect indicators or risk keywords.
* Pay close attention to words like:
  * `bad`, `not working`, `parts only`, `as-is`, `read description`, `defective`, `cracked`, `scratched`, `dents`, `untested`, `no return`, `repairs needed`, `missing parts`.
* If the full description is inaccessible (e.g., eBay 403), note this limitation clearly in the report and assess what you can from the title and search snippets. Positive keywords like "Excellent", "Mint", "Full Set" are good signs.
* Detail any red flags discovered or explicitly state if the description is clean and positive.

### 3. Retrieve Market Value (Recent Sold Listings)
* Determine the target listing's **sale format**: is it **Buy It Now** (fixed price) or **Auction** (with bids)?
* **CRITICAL: Never mix auction sold prices with Buy It Now sold prices.** They represent different buyer pools and nearly always yield different prices. If the target listing is an auction, only use auction-completed sales as comps. If the target is Buy It Now, only use Buy It Now completed sales.
* **CRITICAL: Only use confirmed historical sold prices — never active/asking listings.** An active listing is a seller's wish, not a market reality. Search for completed transactions where the item actually sold.
* **Best sources for sold data (when eBay direct access is blocked):**

  **Source A — eBay category browse with sold/completed filter:** The `/b/` endpoint with `LH_Sold=1&LH_Complete=1` returns only items that actually sold. Use:
  ```
  https://www.ebay.com/b/Jewelry-Watches/31387/bn_7119185158?_nkw={MODEL_NUMBER}&LH_Sold=1&LH_Complete=1&rt=nc
  ```
  Results show final sale prices and bid counts. To distinguish auction from BIN: if the result has a bid count (e.g. "43 bids") it was an auction; if it has no bid count or says "or Best Offer", it was Buy It Now.

  **Source B — WatchCharts** (watchcharts.com) — provides historical market price charts and aggregated sold data. WatchCharts market price is a blended average of sold transactions. Check the price history tab for trend data over time.

  **Source C — EveryWatch** (everywatch.com) — indexes sold eBay listings with prices, dates, conditions, and listing type (auction vs BIN). Filter by "Sold" tab.

  **Source D — Loupe.watch** (loupe.watch) — shows fair market value based on confirmed sold and active listings. The "Sold" tab shows historical transaction data.

  **Source E — General web search** — search for the exact model number + "sold" + "ebay". Filter out results that say "asking" or are listing pages (these are active, not sold).

* Locate at least **3 to 5 recent confirmed sold transactions** from the last 90 days. Clearly label each as **auction** or **Buy It Now**.
* If exact model sold data is scarce, expand to similar models (same collection, movement type, and condition).
* Extract for each:
  * Transaction date.
  * **Final sold price** (specify if excluding/including shipping).
  * **Sale format:** Auction (with bid count) or Buy It Now.
  * Listing title or URL for reference.
  * **Must confirm this is a sold/completed transaction**, not an active listing.

### 4. Price Analysis & Discount Calculation
* Use only the sold prices that match the target listing's sale format:
  * If the target is **auction**: discard all Buy It Now prices; use only auction sold prices.
  * If the target is **Buy It Now**: discard all auction prices; use only BIN sold prices.
* Compute the median of the matching sold prices.
* Calculate the **Target Fair Price** which must be **exactly 30% less** than the median sold price (to ensure a highly profitable deal):
  * `Target Buy Price = Median Sold Price * 0.70`
  * Show your math clearly.

### 5. Final Recommendation
* Compare the current target listing price against your calculated Target Buy Price.
* If the listing is an **ended/completed auction** and the final price is unknown, provide **scenario-based guidance** across price ranges instead of a single recommendation.
* If the listing is **active with a known price**, provide a clear recommendation:
  * **Strong Buy:** Current listing price is at or below the Target Buy Price.
  * **Negotiate / Watch:** Current listing price is slightly higher than Target Buy Price.
  * **Skip:** Current price is too high or listing has severe red flags (e.g. defective).
* The report must clearly state the sale format (Auction vs Buy It Now) and which type of comps were used.

## Output Format
Create a beautifully formatted markdown file named `ebay_research_report.md` inside the `{OUTPUT_DIR}` directory. The file must contain:
1. **Title:** # eBay Research Report: [Brand] [Model Name] [Reference #]
2. **Target Listing Summary Table**
3. **Risk & Red Flag Audit** (with clear emojis like ⚠️ or ✅)
4. **Recent Sold Transactions Table**
5. **Value Analysis & Math** (Average, Median, and 30% Discount calculation)
6. **Final Purchase Recommendation**
