# Tool Interface

## Purpose

Tool containers should be easy to add without changing the control plane for
every new domain. The interface between a worker and the control plane should be
small, stable, and explicit.

## Tool Manifest

Each tool should declare a manifest.

Conceptual fields:

```text
name
version
description
image
capabilities
config schema
required secrets
permissions
resource hints
schedule templates
health endpoint or heartbeat settings
result schemas
artifact types
```

The manifest can be provided in one of two ways:

1. Embedded in the worker image and sent during registration.
2. Stored in the control plane repo and associated with the worker image.

Start with embedded registration. It keeps the container self-describing.

## Capabilities

Capabilities are stable verbs the scheduler and operator can target.

Examples:

```text
ebay.search
ebay.fetch_listing
ebay.score_listing
ebay.recommend_bid
ebay.place_bid
notify.pushover
notify.email
scrape.page
research.summarize
```

Prefer capability names over container names when scheduling work. That allows
multiple worker implementations to serve the same capability later.

## Worker Registration

On startup, a worker should:

1. read its environment
2. authenticate with the control plane
3. register service name, version, capabilities, and instance id
4. send current manifest hash
5. begin heartbeat loop
6. begin job polling/claim loop

Registration should be idempotent. Restarting a container should update the
existing service/instance state rather than creating confusion.

## Heartbeats

Heartbeat payload should include:

- instance id
- service name
- version
- current state
- local queue depth, if any
- active job ids
- resource hints, if available
- timestamp

The control plane should mark an instance stale after missed heartbeats.

## Job Claiming

Workers should ask for work by capability.

Conceptual request:

```text
capabilities: ["ebay.search", "ebay.score_listing"]
max_jobs: 1
lease_seconds: 120
```

Conceptual response:

```text
job_id
capability
input
attempt_number
lease_expires_at
```

The control plane should only return jobs the worker is allowed to execute.

## Progress Events

Workers should publish append-only events:

```text
job.started
job.phase_changed
job.progress
job.warning
job.artifact_created
job.result_partial
job.completed
job.failed
```

Events make the TUI useful and give good audit/debug history.

## Results

Results should be structured JSON with a schema per capability.

The control plane should store:

- raw result
- normalized summary
- artifacts
- external item links
- confidence or score, when relevant
- warnings
- cost/time metrics

For recommendations, always include explanation fields. A score with no reason
is hard to trust.

## Secrets

Workers should never request secret values through normal APIs.

Recommended first version:

- secrets live in server-local environment files or Docker Compose secrets
- worker containers receive only the secrets they need
- control plane stores secret metadata, not values

Later:

- add SOPS/age, Vault, or another secret manager if needed

## Permissions

Each service token should be scoped.

Examples:

```text
service: tool-ebay-research
allowed capabilities:
  - ebay.search
  - ebay.fetch_listing
  - ebay.score_listing
denied capabilities:
  - ebay.place_bid
```

Risky capabilities should require explicit enablement.

## Approval Gates

Capabilities that spend money, send messages externally, modify accounts, or
place bids should require approvals and limits.

Example rules:

```text
ebay.place_bid requires:
  approval for each auction
  max bid amount
  account id
  auction id
  expiration time
  audit reason
```

The worker should fail closed if approval is missing or expired.

## Local Development Mode

Workers should support a development mode:

```text
CONTROL_PLANE_URL=http://localhost:8000
SERVICE_TOKEN=dev-token
DRY_RUN=true
```

Dry-run should still report jobs and results. This makes testing the platform
flow possible before enabling real external actions.

