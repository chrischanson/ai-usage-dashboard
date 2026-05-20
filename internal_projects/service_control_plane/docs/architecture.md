# Architecture

## System Boundary

The service control plane is an internal platform for running many independent
automation services. It should not be coupled to any one domain, including eBay.

The platform boundary is:

```
operator clients
    |
control plane API
    |
central database
    |
tool containers
```

The control plane is responsible for coordination. Tool containers are
responsible for specialized work.

## Components

### Operator Clients

Operator clients are human-facing tools:

- CLI
- TUI
- optional web UI
- optional scripts

They should talk to the control API. They should not manipulate the database
directly.

### Control API

The API is the stable contract for operators and services.

Important API areas:

- `/healthz`
- `/version`
- `/services/register`
- `/services/heartbeat`
- `/jobs`
- `/jobs/claim`
- `/jobs/{id}/renew`
- `/jobs/{id}/events`
- `/jobs/{id}/complete`
- `/jobs/{id}/fail`
- `/schedules`
- `/tools`
- `/approvals`
- `/audit`

The exact paths can change during implementation. The important part is that
these are product-level surfaces, not internal helper calls.

### Control Scheduler

The scheduler should be separate from the API process.

Reasons:

- schedule creation should not compete with API request latency
- scheduler crashes should not take down the API
- API can run multiple replicas later while scheduler remains singleton
- maintenance windows and schedule pauses have one clear owner

The scheduler creates durable job rows. It does not execute tool logic.

### Database

PostgreSQL is the source of truth.

It should hold:

- desired state: schedules, tool configs, limits, permissions
- observed state: heartbeats, jobs, events, results
- durable history: runs, attempts, approvals, audit logs
- dedupe records: external item identities and job idempotency keys

Use database constraints to protect invariants. For example, a unique constraint
on `(source, external_id)` should prevent duplicate eBay listings even if two
workers discover the same item at the same time.

### Tool Containers

Tool containers are independent services. A tool container may be written in
Python, Go, Node, or another runtime, as long as it speaks the worker protocol.

Each container should receive:

```text
CONTROL_PLANE_URL
SERVICE_TOKEN
SERVICE_NAME
INSTANCE_ID
```

Optional values:

```text
LOG_LEVEL
POLL_INTERVAL_SECONDS
MAX_LOCAL_CONCURRENCY
TOOL_CONFIG_PATH
```

### Reverse Proxy and Network

Default access should be private:

- Tailscale for operator access
- Caddy if HTTPS reverse proxy is needed
- firewall allows only SSH, Tailscale, and explicitly approved public services

Tool containers should communicate with the control API over the Compose
network. Operator access can use Tailscale or SSH forwarding.

## Data Flow

### Scheduled Job

```
schedule row
    |
control-scheduler creates job with dedupe key
    |
worker claims job with lease
    |
worker executes
    |
worker publishes events/results
    |
control API writes durable history
```

### Manual Job

```
operator TUI
    |
control API creates job
    |
worker claims job
    |
worker reports result
```

### External Item Discovery

```
worker discovers external item
    |
control API upserts item by stable source/external_id
    |
database returns existing or new item id
    |
worker attaches analysis/recommendation to canonical item
```

## Container Layout

Initial Compose services:

| Service | Purpose |
|---------|---------|
| `postgres` | Central state |
| `control-api` | API for operators and workers |
| `control-scheduler` | Durable schedule-to-job creator |
| `control-tui` | Optional shell entrypoint for local/remote TUI use |
| `tool-ebay-research` | First example worker |
| `caddy` | Optional reverse proxy |

Add Redis or NATS only after there is a measured need for push-based work
delivery or higher throughput.

## Key Architectural Decisions

### API Instead of Direct DB Access

Workers should not write directly to Postgres by default. Direct DB writes make
schema changes harder and spread business rules across every tool.

### Centralized Scheduling

Central scheduling gives one place to pause jobs, enforce limits, prevent
duplicates, and audit behavior.

### Leased Jobs

Workers should claim jobs with leases. If a worker crashes, the lease expires
and the job can be retried.

### Docker Compose First

Compose is the right starting point for one remote server. The design should not
block a later migration to Nomad or Kubernetes, but those are not needed for the
first useful version.

