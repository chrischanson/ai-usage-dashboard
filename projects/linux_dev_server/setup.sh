#!/usr/bin/env bash
# setup.sh
# One-time setup for the always-on host.
# Installs Docker, collects SSH keys, substitutes the host IP into configs,
# starts all services, and creates the Gitea admin user + repository.
#
# Usage:
#   1. Copy .env.example to .env and fill in your values
#   2. Place client SSH public keys in ./ssh-keys/ (one .pub per client)
#   3. Run: ./setup.sh
#
# This script is idempotent — safe to run multiple times.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Load .env ──────────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "ERROR: .env file not found."
    echo "  cp .env.example .env"
    echo "  # Edit .env with your API keys and Gitea credentials"
    exit 1
fi

# shellcheck disable=SC2046
export $(grep -v '^\s*#' "$SCRIPT_DIR/.env" | grep -v '^\s*$' | xargs)

# Defaults from .env (with fallbacks)
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-dev}"
GITEA_ADMIN_PASSWORD="${GITEA_ADMIN_PASSWORD:-changeme123}"
GITEA_ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-dev@localhost}"
GIT_USER_NAME="${GIT_USER_NAME:-Dev User}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-dev@localhost}"
GITEA_REPO="${GITEA_REPO:-main}"

# ── Detect host IP ────────────────────────────────────────────
HOST_IP=$(hostname -I | awk '{print $1}')
echo "Host IP: $HOST_IP"

# ── [1/6] Docker ──────────────────────────────────────────────
echo ""
echo "=== [1/6] Docker ==="
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo ""
    echo "  Docker installed. You may need to log out and back in"
    echo "  for the group change to take effect."
    echo "  Trying 'newgrp docker' for this session..."
    newgrp docker <<DOCKERGROUP
    echo "Docker group applied for this session."
DOCKERGROUP
fi
docker --version
docker compose version

# Ensure Docker buildx plugin is installed to avoid compose warnings
if ! docker buildx version &>/dev/null; then
    echo "Installing Docker Buildx plugin..."
    sudo apt-get update -q && sudo apt-get install -y docker-buildx-plugin || true
fi

# ── [2/6] SSH keys ────────────────────────────────────────────
echo ""
echo "=== [2/6] SSH keys ==="
SSH_KEYS_DIR="$SCRIPT_DIR/ssh-keys"
mkdir -p "$SSH_KEYS_DIR"

KEY_COUNT=$(find "$SSH_KEYS_DIR" -name "*.pub" 2>/dev/null | wc -l)
if [ "$KEY_COUNT" -eq 0 ]; then
    echo ""
    echo "  WARNING: No SSH public keys found in $SSH_KEYS_DIR/"
    echo "  The dev container will not accept connections until you add keys."
    echo ""
    echo "  To add a key:"
    echo "    cp ~/.ssh/id_ed25519.pub $SSH_KEYS_DIR/macbook.pub"
    echo "    scp user@linux-vm:~/.ssh/id_ed25519.pub $SSH_KEYS_DIR/linux-vm.pub"
    echo "  Then restart: docker compose -f server.yml restart dev"
    echo ""
else
    echo "  Found $KEY_COUNT public key(s):"
    find "$SSH_KEYS_DIR" -name "*.pub" | while read -r f; do echo "    $f"; done
fi

# ── [3/6] Prepare configuration ──────────────────────────────
echo ""
echo "=== [3/6] Prepare configuration ==="

# Ensure data directories exist
mkdir -p "$SCRIPT_DIR/gitea/data"
mkdir -p "$SCRIPT_DIR/buildbuddy/data"

# Substitute host IP into .bazelrc template (only if placeholder still present)
BAZELRC="$SCRIPT_DIR/dev-container/bazelrc.template"
if grep -q "HOST_IP_PLACEHOLDER" "$BAZELRC" 2>/dev/null; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|HOST_IP_PLACEHOLDER|${HOST_IP}|g" "$BAZELRC"
    else
        sed -i "s|HOST_IP_PLACEHOLDER|${HOST_IP}|g" "$BAZELRC"
    fi
    echo "  Substituted HOST_IP=$HOST_IP into .bazelrc"
else
    echo "  .bazelrc already configured (no placeholder found)"
fi

# ── [4/6] Build and start containers ─────────────────────────
echo ""
echo "=== [4/6] Build & start containers ==="
cd "$SCRIPT_DIR"
docker compose -f server.yml build dev
docker compose -f server.yml up -d

# ── [5/6] Wait for services to be healthy ────────────────────
echo ""
echo "=== [5/6] Waiting for services to be healthy ==="

wait_for_healthy() {
    local container="$1"
    local max_wait="${2:-120}"
    local waited=0

    printf "  Waiting for %-12s " "$container..."
    while [ $waited -lt $max_wait ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")
        case "$status" in
            healthy)
                echo "✓ healthy (${waited}s)"
                return 0
                ;;
            unhealthy)
                echo "✗ unhealthy after ${waited}s"
                echo "    Logs: docker logs $container"
                return 1
                ;;
            *)
                sleep 2
                waited=$((waited + 2))
                ;;
        esac
    done
    echo "✗ timed out after ${max_wait}s"
    return 1
}

wait_for_healthy "buildbuddy" 60
wait_for_healthy "gitea" 60
wait_for_healthy "dev" 60

echo ""
docker compose -f server.yml ps

# ── [6/6] Configure Gitea + Git inside dev container ─────────
echo ""
echo "=== [6/6] Configure Gitea & Git ==="

# Create Gitea admin user (idempotent — ignores if user exists)
echo "  Creating Gitea admin user '$GITEA_ADMIN_USER'..."
docker exec -u 1000 gitea gitea admin user create \
    --username "$GITEA_ADMIN_USER" \
    --password "$GITEA_ADMIN_PASSWORD" \
    --email "$GITEA_ADMIN_EMAIL" \
    --admin \
    --must-change-password=false 2>/dev/null || \
    echo "  (User already exists — skipping)"

# Create Gitea repository via API (idempotent)
echo "  Creating Gitea repository '$GITEA_REPO'..."
REPO_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "http://localhost:3000/api/v1/user/repos" \
    -H "Content-Type: application/json" \
    -u "$GITEA_ADMIN_USER:$GITEA_ADMIN_PASSWORD" \
    -d "{\"name\": \"$GITEA_REPO\", \"auto_init\": false, \"default_branch\": \"main\"}")

case "$REPO_STATUS" in
    201) echo "  Created repository '$GITEA_REPO'" ;;
    409) echo "  Repository '$GITEA_REPO' already exists — skipping" ;;
    *)   echo "  WARNING: Unexpected response $REPO_STATUS creating repo (check Gitea logs)" ;;
esac

# Configure Git identity and remote inside dev container
echo "  Configuring Git inside dev container..."
docker exec dev bash -c "
    git config --global user.name '${GIT_USER_NAME}' && \
    git config --global user.email '${GIT_USER_EMAIL}' && \
    cd ~/workspace/main && \
    git init 2>/dev/null || true && \
    if git remote get-url origin 2>/dev/null; then
        git remote set-url origin http://gitea:3000/${GITEA_ADMIN_USER}/${GITEA_REPO}.git
    else
        git remote add origin http://gitea:3000/${GITEA_ADMIN_USER}/${GITEA_REPO}.git
    fi && \
    echo "http://${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}@gitea:3000" > ~/workspace/.git-credentials && \
    chmod 600 ~/workspace/.git-credentials && \
    echo 'Git remote set to: http://gitea:3000/${GITEA_ADMIN_USER}/${GITEA_REPO}.git' && \
    echo 'Git credentials stored in: ~/workspace/.git-credentials'
"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  All services running!"
echo "========================================"
echo ""
echo "  Dev container SSH:  ssh devserver"
echo "  Gitea web UI:       http://${HOST_IP}:3000"
echo "  BuildBuddy web UI:  http://${HOST_IP}:8080"
echo ""
echo "  Gitea admin:        ${GITEA_ADMIN_USER} / (password in .env)"
echo "  Gitea repository:   http://${HOST_IP}:3000/${GITEA_ADMIN_USER}/${GITEA_REPO}"
echo ""
echo "── Client: MacBook (Antigravity / Windsurf) ────────────"
echo "  Add to ~/.ssh/config:"
echo "     Host devserver"
echo "       HostName ${HOST_IP}"
echo "       Port 2220"
echo "       User dev"
echo "       IdentityFile ~/.ssh/id_ed25519"
echo ""
echo "  In Antigravity or Windsurf:"
echo "    Cmd+Shift+P -> 'Remote-SSH: Connect to Host' -> devserver"
echo "    Open folder: /home/dev/workspace/main"
echo ""
echo "── Client: Linux VM ────────────────────────────────────"
echo "  Run setup_linux_client.sh on the Linux VM."
echo "  See that script for full instructions."
echo ""
echo "── Adding SSH keys later ───────────────────────────────"
echo "  cp <new-key>.pub $SSH_KEYS_DIR/<client-name>.pub"
echo "  docker compose -f server.yml restart dev"
echo ""
echo "── Day-to-day commands ─────────────────────────────────"
echo "  Stop all:      docker compose -f server.yml down"
echo "  Start all:     docker compose -f server.yml up -d"
echo "  Rebuild dev:   docker compose -f server.yml build dev && docker compose -f server.yml up -d dev"
echo "  View logs:     docker compose -f server.yml logs -f <service>"
echo ""
echo "── Backup ──────────────────────────────────────────────"
echo "  Gitea + BB:    tar czf backup-data.tar.gz gitea/ buildbuddy/"
echo "  Workspace:     docker run --rm -v dev-home:/data -v \$(pwd):/backup busybox tar czf /backup/workspace-backup.tar.gz -C /data ."
echo ""
