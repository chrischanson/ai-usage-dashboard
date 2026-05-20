# Roadmap

## Phase 0 - Planning and Contracts

Outcome: the platform has a stable shape before code starts.

Tasks:

- finalize architecture
- define worker protocol
- define initial database entities
- define job lifecycle
- define service token and permission model
- define deploy/rollback expectations
- define first worker use case

Exit criteria:

- docs explain how a new service plugs in
- scheduling and dedupe model are clear
- MVP scope is small enough to implement

## Phase 1 - Control Plane Skeleton

Outcome: a local control plane can accept services and jobs.

Build:

- FastAPI service
- PostgreSQL connection
- migrations
- health/version endpoints
- service registration
- service heartbeat
- job creation
- job claiming with leases
- job completion/failure
- basic event log

Exit criteria:

- a fake worker can claim and complete jobs
- stale leases can be retried
- duplicate job keys are rejected or merged

## Phase 2 - CLI/TUI Operator Console

Outcome: terminal-first operation is comfortable.

Build:

- CLI command group
- TUI dashboard
- service list/status
- job list/detail
- job event tail
- manual job creation
- retry/cancel controls
- schedule list/toggle

Exit criteria:

- normal operations do not require database access
- user can understand current system state from the TUI

## Phase 3 - Scheduler

Outcome: durable schedules create jobs centrally.

Build:

- schedule records
- interval and cron support
- timezone support
- enable/disable controls
- dedupe windows
- scheduler heartbeat
- schedule event/audit records

Exit criteria:

- a schedule creates exactly one expected job per window
- disabling a schedule prevents new jobs
- missed or duplicate scheduler loops do not create duplicate jobs

## Phase 4 - First Real Worker

Outcome: the first independent tool container proves the protocol.

Recommended first worker:

- eBay research, recommendation-only
- no automatic bidding
- official APIs first
- dry-run by default

Build:

- worker registration
- capabilities
- job polling
- job execution
- result publishing
- external item upsert through control API
- recommendation result schema

Exit criteria:

- worker runs as its own Docker container
- control plane shows status and history
- duplicate external items collapse into one canonical record

## Phase 5 - Deployment Workflow

Outcome: remote updates are repeatable.

Build:

- Compose stack
- image build/push
- deploy command
- migration step
- health check step
- rollback metadata
- server `.env`/secret layout

Exit criteria:

- one command can update the remote server
- failed health checks stop the deploy or roll back
- previous image tag is preserved

## Phase 6 - Permissions and Approvals

Outcome: risky tools can be added safely.

Build:

- scoped service tokens
- role-based operator permissions
- approval queue
- per-capability limits
- audit log
- dry-run/real-run distinction
- spending/action limits

Exit criteria:

- no tool can perform risky actions without explicit permission
- approvals are visible in TUI
- audit history is complete enough to investigate actions

## Phase 7 - Optional Web UI

Outcome: visual review becomes pleasant.

Build only after CLI/TUI and API are stable.

Good web UI use cases:

- recommendation cards
- item image comparison
- historical result browsing
- approval review
- dashboards

Do not make the web UI the control plane itself. It should remain another API
client.

## Deferred Decisions

Consider later:

- Redis or NATS for push-based job dispatch
- Caddy public exposure
- SOPS/age or Vault for secrets
- multi-host orchestration
- Nomad or Kubernetes
- dynamic tool installation from a registry
- browser automation workers
- auto-bidding or other irreversible external actions

