# Service Control Plane — Overview

## Goal Statement

Create a reusable self-hosted framework that deploys and operates many
independent Dockerized services from one control plane. The framework should make
it easy to add new tools without rebuilding the operational plumbing each time.

The first motivating example is an eBay research and bidding assistant, but the
framework must stay generic. A future tool should be able to register itself,
declare capabilities, receive jobs, publish results, and rely on the central
system for scheduling, deduplication, configuration, secrets, logs, and audit
history.

## Glossary

These terms have specific meanings throughout the documentation:

| Term | Definition |
|------|------------|
| Service | A registered tool type (e.g., `ebay-research`). One service may have many running instances. |
| Instance | A running container of a service, identified by a unique instance id. |
| Capability | A stable verb an instance can perform (e.g., `ebay.search`). Schedules and jobs target capabilities, not containers. |
| Job | A durable execution request targeting a capability. Created by schedules, operators, or workers. |
| Run | A single attempt to execute a job. A job may have multiple runs across retries. |
| Schedule | A rule that creates jobs on a recurring basis (cron or interval). |
| External Item | A deduplicated record of an outside-world object (e.g., an eBay listing), identified by source + external id. |

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

## MVP Definition

MVP is complete when:

1. A remote Compose stack runs Postgres, the control API, the scheduler, and one
   worker container.
2. The worker can register, heartbeat, claim jobs, renew leases, and report
   results.
3. The scheduler can create jobs from schedule records.
4. Duplicate jobs and duplicate external items are blocked by database
   constraints.
5. A CLI can show service status, job status, logs/events, manual runs,
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
- full TUI dashboard (CLI is sufficient; rich TUI follows in a later phase)

## Documentation Map

Detailed design lives in a dedicated document per topic. Each is the single
source of truth for its area:

| Document | Covers |
|----------|--------|
| [architecture.md](docs/architecture.md) | Components, responsibilities, data flow, container layout, operator interface, security model |
| [scheduling-and-concurrency.md](docs/scheduling-and-concurrency.md) | Scheduling model, job lifecycle, dedup, concurrency, retries, cancellation |
| [tool-interface.md](docs/tool-interface.md) | Worker protocol, manifests, capabilities, secrets, permissions, approvals |
| [deployment.md](docs/deployment.md) | Docker, registry, deploy flow, rollback, health checks, backups, access |
| [roadmap.md](docs/roadmap.md) | Implementation phases and decision gates |
| [ebay-tool-example.md](docs/ebay-tool-example.md) | First worker use case and safety boundaries |
