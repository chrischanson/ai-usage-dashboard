# Roadmap

## Phase 1 — Contracts

Outcome: the platform has a stable shape before code starts.

Tasks:

- finalize architecture
- define worker protocol (Phase 2 scope — see tool-interface.md)
- define initial database entities and sketch table layout
- define job lifecycle states
- define service token and permission model (stub for Phase 2, full design for Phase 5)
- define deploy/rollback expectations
- define first worker use case

Exit criteria:

- docs explain how a new service plugs in
- scheduling and dedupe model are clear
- MVP scope is small enough to implement
- a rough entity-relationship sketch exists for the core tables

## Phase 2 — Core Platform

Outcome: the control plane can accept services, create scheduled jobs, and
complete the full job lifecycle with a fake worker.

This phase combines the API skeleton and the scheduler into one deliverable.
Building them together means the end-to-end flow (schedule → job → claim →
result) can be tested before any real tool or operator UI exists.

Build:

- FastAPI service with health/version endpoints
- PostgreSQL connection and Alembic migrations
- service registration and heartbeat
- job creation and job claiming with leases
- job completion, failure, and basic event log
- schedule records with interval and cron support
- timezone support and enable/disable controls
- dedupe windows for schedule-created jobs
- scheduler heartbeat and audit records
- stub authentication (shared secret in environment)

Worker protocol scope for this phase (minimal):

- `POST /services/register` — register name, version, capabilities
- `POST /services/heartbeat` — report alive
- `POST /jobs/claim` — request a job by capability
- `POST /jobs/{id}/complete` and `POST /jobs/{id}/fail` — report outcome

Deferred to later phases:

- progress events, partial results, artifact creation
- lease renewal (use generous initial leases instead)
- approval checks during claiming

Exit criteria:

- a fake worker can register, claim, and complete jobs
- stale leases are retried
- duplicate job dedupe keys are rejected
- the scheduler creates exactly one job per schedule window
- disabling a schedule prevents new jobs
- missed or duplicate scheduler loops do not create duplicate jobs

## Phase 3 — First Real Worker + Deploy

Outcome: a real tool container proves the protocol end-to-end, and remote
deployment is repeatable.

Building the first worker and the deploy pipeline together means the protocol
gets tested under real conditions and the full lifecycle (code change → deploy →
job execution → result) is validated.

### Worker

Recommended first worker: eBay research, recommendation-only (see
ebay-tool-example.md).

Build:

- worker registration with capabilities
- job polling and execution
- result publishing
- external item upsert through control API
- recommendation result schema

### Deployment

Build:

- Docker Compose stack definition
- image build and push to registry
- deploy command (SSH to remote, pull images, run migrations, restart, health-check)
- rollback metadata (stored as a deployment state file on the server)
- server environment and secret file layout

Exit criteria:

- worker runs as its own Docker container on the remote server
- duplicate external items collapse into one canonical record
- one command can update the remote server
- failed health checks stop the deploy or roll back
- previous image tags are preserved for rollback

## Phase 4 — Operator Console

Outcome: terminal-first operation is comfortable. Built against real data from
the running worker.

### CLI Commands

Build first:

```
control status
control services
control jobs
control jobs retry <id>
control jobs cancel <id>
control schedules
control schedules pause <id>
control run <capability> --input ...
```

### TUI Dashboard

Build after the CLI commands work:

- service list/status with live refresh
- job list/detail
- job event tail
- manual job creation form
- retry/cancel controls
- schedule list/toggle

Exit criteria:

- normal operations do not require database access
- operator can understand current system state from the CLI or TUI

## Phase 5 — Safety and Polish

Outcome: risky tools can be added safely, and optionally reviewed in a web UI.

### Permissions and Approvals

Build:

- scoped service tokens
- role-based operator permissions
- approval queue
- per-capability limits
- audit log
- dry-run/real-run distinction
- spending/action limits

### Extended Worker Protocol

Add if needed by real usage:

- progress events and partial results
- lease renewal for long-running jobs
- artifact creation and attachment
- per-source and per-account concurrency limits

### Optional Web UI

Build only after CLI/TUI and API are stable.

Good web UI use cases:

- recommendation cards with images
- item comparison
- historical result browsing
- approval review
- dashboards

The web UI should remain another API client. It should not become the control
plane itself.

Exit criteria:

- no tool can perform risky actions without explicit permission
- approvals are visible in CLI/TUI
- audit history is complete enough to investigate actions

## Deferred Decisions

Consider after the MVP phases:

- Redis or NATS for push-based job dispatch
- Caddy public exposure
- SOPS/age or Vault for secrets
- multi-host orchestration
- Nomad or Kubernetes
- dynamic tool installation from a registry
- browser automation workers
- auto-bidding or other irreversible external actions
