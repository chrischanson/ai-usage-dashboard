# Service Control Plane

Reusable self-hosted framework for running independent tool services as Docker
containers, while keeping scheduling, deduplication, configuration, audit logs,
and operational control centralized.

The control plane is intentionally generic. An eBay research or auto-bidder
service can be the first real tool, but the framework should also support future
services such as price monitors, notification bots, media processors, research
agents, backup jobs, and other long-running automation.

## Core Idea

```
operator CLI/TUI
    |
    v
control plane API + scheduler + database
    |
    v
independent tool containers
```

The control plane owns:

- service identity and registration
- central database and deduplication
- schedules and job creation
- job leases, retries, cancellation, and concurrency limits
- tool configuration and secret metadata
- audit logs and operator approvals
- deployment metadata and health visibility

Tool containers own:

- domain-specific behavior
- external API calls
- scoring, scraping, enrichment, or action logic
- progress events and result publication through the control plane API

Workers should not write directly to the central database in the default design.
They talk to the API so the control plane remains the stable contract.

## Documentation Map

| File | Purpose |
|------|---------|
| `plan.md` | Main product and architecture plan |
| `docs/architecture.md` | System components and responsibilities |
| `docs/scheduling-and-concurrency.md` | Scheduling model, leases, retries, and deduplication |
| `docs/tool-interface.md` | Worker service contract and manifest design |
| `docs/deployment.md` | Docker, registry, server, and update workflow |
| `docs/roadmap.md` | Implementation phases and decision gates |
| `docs/ebay-tool-example.md` | Example first tool and safety boundaries |

## Recommended Starting Point

Build the minimum useful control plane first:

1. API server with health, service registration, job creation, job leasing, and
   result recording.
2. PostgreSQL schema for services, jobs, runs, external items, dedupe keys, and
   audit logs.
3. CLI/TUI operator interface for status, logs, manual runs, retries, and
   schedule toggles.
4. Scheduler service that creates durable jobs from schedule records.
5. One worker container that uses the generic worker protocol.

Do not start with a full web dashboard, plugin marketplace, Kubernetes, or
high-risk automation actions. The first goal is a small reliable platform that
can run many containers without losing track of work.

