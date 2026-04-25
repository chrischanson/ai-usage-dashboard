# 🐳 docker-standalone-to-compose

A collection of professional shell tools to seamlessly transition standalone Docker containers to structured Docker Compose stacks, and to safely automate their updates.

## 🛠 Tools

### 1. `docker-migrate.sh`
A robust migration engine that inspects running standalone containers and reverse-engineers a complete, property-mapped `docker-compose.yml` file.

**Features:**
- **Auto-Environment Extraction:** Intelligently detects and fixes common `docker run` mistakes (like `-e` flags passed as command arguments) by rescuing them into the `environment:` section.
- **Precise Image Verification:** Uses the **original image SHA** that built the container to accurately identify custom overrides, avoiding "false positives" from newly pulled tags.
- **Compose-Safe YAML:** Automatically escapes `$` characters as `$$` to prevent Compose from interpreting strings like password hashes as variables.
- **Volume Preservation:** Detects anonymous volumes and explicitly maps them as named volumes to prevent data loss upon recreation.

### 2. `docker-update.sh`
A zero-downtime, bulk update utility that safely pulls new images and restarts all Compose stacks (`.yml` files) in the current directory.

**Features:**
- **Dependency Checking:** Automatically verifies `docker` and `docker compose` prerequisites.
- **Conflict Resolution:** Intelligently parses your YAML files using Python to find defined container names, and forcefully cleans up any conflicting standalone containers that might block the compose startup.
- **Visual Summary Output:** Provides a clear success/failure summary table for all processed stacks at the end of the run.

## 🚀 Usage

### Migration

```bash
# Dry Run: Preview the Compose YAML for a running container
./docker-migrate.sh -c <container_name>

# Execute: Write the properties to a docker-compose.yml file
./docker-migrate.sh -c <container_name> --write
```

### Stack Updates
To fetch the latest images and refresh deployments:

```bash
# Update all stacks in the folder
./docker-update.sh

# Update only specific stacks
./docker-update.sh ddns dev-server

# Build and recreate a specific service (no-cache) across all projects
./docker-update.sh --build web

# Force recreate even if images haven't changed
./docker-update.sh --force ddns
```
