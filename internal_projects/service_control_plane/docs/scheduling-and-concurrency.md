# Scheduling and Concurrency

## Recommendation

Use centralized scheduling by default.

```
control-scheduler creates jobs
workers claim jobs
workers execute jobs
control plane records all outcomes
```

Workers may have local loops for polling and heartbeats, but they should not run
real scheduled work without first obtaining a job or lease from the control
plane.

## Why Not Worker-Owned Cron by Default

Worker-owned cron looks simple but creates platform problems:

- duplicate jobs across restarted containers
- no central pause button
- hard-to-answer "what is running now?"
- inconsistent retry behavior
- scattered rate limit enforcement
- unclear audit trail
- collisions when multiple replicas of the same worker run

Central scheduling solves those problems early.

## Hybrid Autonomous Mode

Some workers may need to wake themselves up. For example, a worker may monitor a
local queue, respond to a webhook, or perform a quick local health probe.

The rule:

```
worker may wake itself
worker must request a run lease before doing platform-visible work
```

The control plane can approve or deny the run based on dedupe keys, limits,
paused schedules, maintenance windows, and permissions.

## Schedule Records

A schedule should describe:

- schedule id
- tool or capability
- input template
- cron or interval
- timezone
- enabled/disabled state
- dedupe policy
- concurrency policy
- retry policy
- owner
- audit metadata

Example conceptual schedule:

```text
id: ebay-camera-lens-search
capability: ebay.search
interval: every 30 minutes
timezone: America/Los_Angeles
input:
  query: "sony e mount lens"
  max_price: 300
dedupe_window: 30 minutes
max_concurrent: 1
enabled: true
```

## Job Records

A job is a durable execution request.

Important fields:

- id
- job type or capability
- input JSON
- status
- priority
- dedupe key
- idempotency key
- schedule id, if scheduled
- created at
- available after
- attempt count
- max attempts
- claimed by
- lease expires at
- cancellation requested flag

## Job States

```
queued
leased
running
succeeded
failed
retry_queued
cancel_requested
cancelled
dead_lettered
```

Implementation can simplify early, but the data model should leave room for
these states.

## Leasing

Workers claim jobs with a finite lease:

```text
job_id
claimed_by service_instance_id
lease_expires_at
attempt_number
```

Long-running jobs must renew their lease. If the worker dies or loses
connectivity, the lease eventually expires and the job can be retried.

## Claiming Rules

A worker can claim a job only when:

- the job is queued and available
- the worker has the required capability
- the service token is authorized
- global concurrency limits allow it
- per-capability limits allow it
- per-target/source limits allow it
- schedule/tool is not paused
- required approval exists, if needed

## Deduplication

Use two layers:

### Job Deduplication

Prevents the same work from being queued repeatedly.

Example dedupe keys:

```text
ebay.search:query=sony-lens:window=2026-05-20T10:00Z
ebay.score_listing:item=123456789
notify:item=123456789:channel=pushover
```

### External Item Deduplication

Prevents duplicate records for the same outside-world object.

Example:

```text
source: ebay
external_id: listing id
```

Other useful fields:

- canonical URL
- normalized title
- content hash
- first seen timestamp
- last seen timestamp

## Concurrency Limits

Concurrency should be enforceable at multiple scopes:

| Scope | Example |
|-------|---------|
| Global | No more than 20 jobs running across the whole platform |
| Tool | No more than 4 eBay research jobs |
| Capability | No more than 2 `ebay.search` jobs |
| Source | No more than 3 jobs hitting eBay APIs |
| Account | No more than 1 job using a specific eBay account |
| Action | No more than 1 `place_bid` job, approval required |

Start simple with global, per-tool, and per-capability limits. Add source and
account limits before risky or rate-limited integrations.

## Retries

Retry policy should include:

- max attempts
- backoff strategy
- retryable error types
- non-retryable error types
- dead-letter state

Some failures should not retry automatically:

- authentication failure
- permission denied
- invalid configuration
- action limit exceeded
- policy violation

Network timeouts and transient external API failures can retry.

## Cancellation

Cancellation should be cooperative.

Flow:

```
operator requests cancellation
control plane marks cancel_requested
worker sees flag during heartbeat/renewal/progress update
worker stops safely
worker marks cancelled
```

For dangerous actions, cancellation behavior must be documented. Some actions
cannot be undone once sent to an external system.

## Scheduler Singleton

The first version can run exactly one scheduler container.

Later, if multiple scheduler replicas are needed, use database advisory locks or
leader election so only one active scheduler creates jobs at a time.

