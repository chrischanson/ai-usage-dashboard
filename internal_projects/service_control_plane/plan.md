# Service Control Plane - System Plan v0.1

## Goal Statement

Create a reusable self-hosted framework that deploys and operates many
independent Dockerized services from one control plane. The framework should make
it easy to add new tools without rebuilding the operational plumbing each time.

The first motivating example is an eBay research and bidding assistant, but the
framework must stay generic. A future tool should be able to register itself,
declare capabilities, receive jobs, publish results, and rely on the central
system for scheduling, deduplication, configuration, secrets, logs, and audit
history.

## Design Principles

1. The control plane is the source of truth.
2. Tool services run as independent Docker containers.
3. The central database prevents duplicate work and duplicate records.
4. Scheduling decisions are centralized by default.
5. Workers execute work through leased jobs, not ad hoc cron loops.
6. Workers communicate through the control plane API, not direct database writes.
7. Risky actions require explicit permissions, limits, audit logs, and approval
   gates.
8. CLI/TUI is the primary operator interface; web UI can be added later for rich
   visual review.

## Target Architecture

```
local workstation
    |
    | deploy command
    v
container registry
    |
    | image pull
    v
remote server
    |
    +-- caddy or tailscale access
    +-- control-api
    +-- control-scheduler
    +-- postgres
    +-- optional redis or nats later
    +-- tool-ebay-research
    +-- tool-notifier
    +-- tool-price-monitor
    +-- future tools
```

## Selected Tools

| Area | Choice | Rationale |
|------|--------|-----------|
| Runtime | Docker Engine + Docker Compose | Simple single-server orchestration with clear service boundaries. |
| Image build | Docker Buildx | Builds immutable images and pushes to a registry. |
| Registry | GitHub Container Registry | Good default for private images tied to source repositories. |
| Deploy transport | SSH-driven deploy script | Transparent, debuggable, and enough for a single remote host. |
| Backend API | FastAPI | Strong Python ecosystem, async support, OpenAPI docs, typed models. |
| Data validation | Pydantic | Natural fit with FastAPI and worker manifests/config schemas. |
| Database | PostgreSQL | Durable central source of truth with constraints, JSONB, indexes, and transactions. |
| Migrations | Alembic + SQLAlchemy | Versioned schema evolution. |
| Scheduler | Dedicated control-scheduler service | Creates durable jobs from schedules in the central database. |
| Operator UI | Typer CLI + Textual/Rich TUI | Comfortable terminal workflow with room for dashboards and log views. |
| Reverse proxy | Caddy | Simple HTTPS reverse proxy if exposing an HTTP API or web UI. |
| Private network | Tailscale | Good default for private admin access. |
| Optional queue later | Redis or NATS | Add only if DB polling/wakeup becomes a bottleneck. |

## Core Components

### Control API

Responsibilities:

- authenticate operators and services
- register service instances
- expose service and job status
- create manual jobs
- allow workers to claim jobs with leases
- accept progress events, results, artifacts, and failures
- enforce idempotency and deduplication
- expose schedule, configuration, and audit records to the CLI/TUI

### Control Scheduler

Responsibilities:

- read schedule definitions from the database
- create jobs at the right time
- use dedupe keys so schedules cannot create duplicate jobs
- honor disabled schedules and maintenance windows
- apply global and per-capability concurrency limits before releasing jobs

The scheduler should be a separate process/container from the API. This keeps
API request handling independent from periodic schedule work.

### PostgreSQL Database

Stores:

- services and live service instances
- tool manifests and capabilities
- schedules
- jobs and job runs
- job events and logs
- external items and dedupe keys
- recommendations, artifacts, and result summaries
- secret metadata
- approvals and audit logs

PostgreSQL should be the initial durable job queue. Use transactions and
`SELECT ... FOR UPDATE SKIP LOCKED` style claiming when implementation begins.

### Worker Containers

Every tool service should:

- start independently as a Docker container
- authenticate to the control plane with a service token
- register its manifest and current instance metadata
- heartbeat periodically
- claim jobs matching its capabilities
- execute jobs locally
- publish progress and results through the API
- renew leases during long jobs
- stop cleanly on cancellation or shutdown

## Scheduling Model

Use centralized scheduling by default:

```
schedule record -> scheduler creates job -> worker claims job -> worker executes
```

This avoids the common failure mode where every tool invents its own cron,
causing duplicate runs, unclear retries, and poor visibility.

Support a hybrid escape hatch:

```
autonomous worker wakes itself -> requests run lease -> control plane allows or denies
```

This lets special workers operate independently while still preserving central
dedupe, audit, and concurrency control.

## Job Lifecycle

```
queued
  -> leased
  -> running
  -> succeeded
```

Failure paths:

```
queued -> leased -> running -> failed -> retry_queued
queued -> leased -> lease_expired -> retry_queued
queued -> cancelled
running -> cancel_requested -> cancelled
```

The control plane should track:

- status
- attempt number
- claimed_by instance
- lease expiration
- progress percentage or current phase
- start and finish times
- error type and error message
- idempotency key
- dedupe key

## Deduplication Strategy

The database should enforce duplicate prevention instead of relying on careful
worker behavior.

External records should use stable identities:

```
source: ebay
external_id: listing id
canonical_url
content_hash
first_seen_at
last_seen_at
```

Jobs should use dedupe keys:

```
job_type + target + schedule_window
```

Examples:

```
ebay.search:query=lens:window=2026-05-20T10:00Z
ebay.score_listing:item_id=123456789
notify.recommendation:item_id=123456789:channel=pushover
```

## Concurrency Control

The control plane should enforce:

- global max concurrent jobs
- per-service max concurrent jobs
- per-capability max concurrent jobs
- per-source max concurrent jobs
- per-account max concurrent jobs
- action-specific limits for risky operations

Example:

| Capability | Limit |
|------------|-------|
| `ebay.search` | 2 concurrent jobs |
| `ebay.score_listing` | 4 concurrent jobs |
| `ebay.recommend_bid` | 2 concurrent jobs |
| `ebay.place_bid` | 1 concurrent job, approval required |

## Interface Strategy

Primary interface:

```
control status
control services
control jobs
control jobs retry <id>
control jobs cancel <id>
control schedules
control schedules pause <id>
control run <capability> --input ...
control tui
```

The TUI should support:

- live service health
- active jobs
- schedule toggles
- job logs and events
- manual run forms
- retries and cancellation
- approval queue
- recommendation review

The web UI should be optional and added after the API/TUI are stable.

## Security Model

Start private by default:

- access through Tailscale or SSH tunnel
- service tokens scoped to capabilities
- operator tokens scoped to roles
- secrets stored only on the server
- secret values never returned through APIs
- all risky actions written to the audit log
- spend/action limits enforced in the control plane

Avoid mounting the Docker socket into the API container. It is effectively root
on the host. Let the deploy script and Compose manage containers instead.

## MVP Definition

MVP is complete when:

1. A remote Compose stack runs Postgres, the control API, the scheduler, and one
   worker container.
2. The worker can register, heartbeat, claim jobs, renew leases, and report
   results.
3. The scheduler can create jobs from schedule records.
4. Duplicate jobs and duplicate external items are blocked by database
   constraints.
5. The TUI can show service status, job status, logs/events, manual runs,
   retries, cancellations, and schedule toggles.
6. A deploy command can build, push, update, migrate, restart, and health-check
   the stack.

## Non-Goals for MVP

- Kubernetes
- public marketplace for plugins
- direct database access from worker containers
- web UI as the primary interface
- automatic money-spending actions
- browser automation as the default integration strategy
- multi-server orchestration

