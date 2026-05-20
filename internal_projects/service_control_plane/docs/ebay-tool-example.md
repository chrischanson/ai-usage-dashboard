# eBay Tool Example

## Purpose

The eBay tool is a useful first real worker because it exercises the framework:

- schedules
- external API integration
- deduplication
- item identity
- recommendations
- artifacts
- approvals, eventually
- potentially risky actions, later

The first version should be recommendation-only.

## Initial Capabilities

Start with:

```text
ebay.search
ebay.fetch_listing
ebay.score_listing
ebay.recommend_bid
```

Defer:

```text
ebay.place_bid
```

## Recommended First Workflow

```
schedule creates ebay.search job
    |
worker searches for listings
    |
worker upserts external items by ebay listing id
    |
worker creates scoring jobs or scores inline
    |
worker publishes recommendations
    |
operator reviews in TUI or future web UI
```

## Data to Capture

For each listing:

- source: `ebay`
- external listing id
- title
- canonical URL
- seller id or seller summary
- current price
- shipping price
- auction end time
- condition
- item specifics
- image URLs
- first seen time
- last seen time
- raw API payload reference or sanitized snapshot

For each recommendation:

- score
- confidence
- max recommended bid
- reasoning
- comparable items, if available
- risk flags
- created by worker/version
- associated job id

## Deduplication

Use the eBay listing id as the primary external id when available.

If a listing id is missing, use a fallback content hash based on normalized
title, seller, price, and URL. The fallback should be considered weaker and
should be marked as such.

## Safety Boundary

Do not implement automatic bidding in the first platform phase.

Before bidding is allowed, the platform needs:

- scoped permission for `ebay.place_bid`
- explicit account selection
- per-auction approval
- max bid limit
- expiration time for approval
- dry-run mode
- audit log
- external policy review
- clear cancellation semantics

The control plane should treat `ebay.place_bid` as a high-risk capability.

## Suggested Job Types

```text
ebay.search
  input:
    query
    max_price
    condition filters
    category
    auction_only

ebay.score_listing
  input:
    external_item_id
    user_preferences

ebay.recommend_bid
  input:
    external_item_id
    max_budget
    strategy

ebay.place_bid
  input:
    external_item_id
    bid_amount
    approval_id
```

## Operator Experience

The TUI should support:

- show new recommendations
- sort by score, end time, price, confidence
- view recommendation explanation
- mark as ignored
- mark as interesting
- create approval for a future action, once risky actions are supported

The future web UI is valuable here because listings have images and visual
comparison matters. The TUI remains the operational interface.

