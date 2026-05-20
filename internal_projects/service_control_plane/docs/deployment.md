# Deployment Plan

## Deployment Goal

Make updates boring:

```
make code changes
run deploy command
remote server pulls new images
database migrations run
services restart
health checks pass
```

The remote server should not need a full source checkout for normal operation.
It should run Compose files, environment/secrets files, and image tags.

## Server Model

Recommended initial server:

- Ubuntu 24.04 LTS or similar
- Docker Engine
- Docker Compose plugin
- SSH access
- Tailscale
- firewall enabled
- persistent volume for Postgres data
- backup directory or mounted backup target

## Image Registry

Use GitHub Container Registry first.

Images:

```text
ghcr.io/<owner>/service-control-api:<git-sha>
ghcr.io/<owner>/service-control-scheduler:<git-sha>
ghcr.io/<owner>/service-control-tui:<git-sha>
ghcr.io/<owner>/tool-ebay-research:<git-sha>
```

Avoid mutable deployment tags as the only source of truth. The server should
know the exact git SHA/image digest it is running.

## Compose Stack

Initial services:

```text
postgres
control-api
control-scheduler
tool-ebay-research
caddy, optional
```

Future services:

```text
redis or nats
control-web
tool-notifier
tool-price-monitor
tool-scraper
```

Use Compose profiles for optional tools:

```text
profile: ebay
profile: notifications
profile: web
```

This lets the same framework run different tool sets on different hosts.

## Deploy Flow

Conceptual deploy command:

```text
control deploy production
```

Steps:

1. verify git working tree policy
2. run tests
3. build images
4. tag images with git SHA
5. push images to registry
6. SSH to remote server
7. update deployment metadata with new image tags
8. pull images
9. run database migrations
10. restart changed services
11. wait for health checks
12. show deployed versions
13. preserve previous deployment metadata for rollback

## Rollback

Rollback should use the previous known-good image tags.

Conceptual command:

```text
control rollback production
```

Rollback steps:

1. load previous deployment metadata
2. switch image tags back
3. restart services
4. run compatibility checks
5. verify health

Database rollbacks require more care. Prefer forward-compatible migrations and
avoid destructive schema changes until there is a backup/restore process.

## Health Checks

Required checks:

- control API `/healthz`
- database connectivity
- scheduler heartbeat
- worker heartbeat
- pending migration state

Useful checks:

- service version endpoint
- active job count
- stale lease count
- failed job count in last hour
- disk free space
- Postgres backup freshness

## Backups

Back up Postgres before serious automation work.

Minimum:

- daily `pg_dump`
- retention policy
- restore test process

Backups should include:

- platform state
- schedules
- job/run history
- recommendations
- audit logs

Do not store raw secret values in the database unless a proper secret management
strategy is in place.

## Access

Default:

- Tailscale for private access
- SSH for deployment
- Caddy only if exposing HTTP routes is needed

Do not expose the control API publicly until authentication, authorization,
rate limits, and audit logs are in place.

## Avoid Docker Socket in API

Do not mount `/var/run/docker.sock` into the control API for the MVP.

Reasons:

- Docker socket access is effectively root on the host
- compromised API would compromise the whole server
- Compose/deploy script is enough for controlled updates

If dynamic container orchestration is needed later, add a narrowly scoped
host-side agent with a very small API rather than giving the main app raw Docker
control.

