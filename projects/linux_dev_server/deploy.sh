#!/usr/bin/env bash
# deploy.sh
# Deploys the linux_dev_server project to the host machine.
#
# Clones (or pulls) the repo from Gitea, then syncs the project files
# into the target directory alongside other compose stacks.
#
# The dev-container/ subdirectory is preserved (needed for image builds),
# but the compose file (server.yml) sits at the top level so docker-update.sh
# discovers it alongside other .yml stacks.
#
# Usage:
#   ./deploy.sh                          # Deploy to ~/dev-services (default)
#   ./deploy.sh /opt/docker-services     # Deploy to a custom directory
#
# Prerequisites: git, access to Gitea at localhost:3000
set -euo pipefail

TARGET_DIR="${1:-$HOME/dev-services}"
GITEA_URL="http://localhost:3000"
REPO_NAME="linux_dev_server"
REPO_REMOTE="${GITEA_URL}/dev/${REPO_NAME}.git"
CLONE_DIR="${TARGET_DIR}/.repos/${REPO_NAME}"

# ── Ensure target directory exists ────────────────────────────
mkdir -p "$TARGET_DIR"

# ── Clone or pull the repo ────────────────────────────────────
if [[ -d "$CLONE_DIR/.git" ]]; then
    echo "==> Pulling latest changes..."
    git -C "$CLONE_DIR" pull --ff-only
else
    echo "==> Cloning ${REPO_REMOTE}..."
    mkdir -p "$(dirname "$CLONE_DIR")"
    git clone "$REPO_REMOTE" "$CLONE_DIR"
fi

# ── Sync files into target directory ──────────────────────────
# Structure on host:
#   ~/dev-services/
#     server.yml              ← compose file (top-level for docker-update.sh)
#     .env                     ← secrets (never overwritten if it exists)
#     .env.example             ← template
#     .gitignore
#     docker-update.sh         ← shared update script
#     dev-container/           ← build context for the dev service
#     gitea/                   ← persistent data
#     buildbuddy/              ← persistent data
#     ssh-keys/                ← client public keys
#     setup.sh
#     setup_linux_client.sh
#     SETUP_GUIDE.md
#     .repos/linux_dev_server/ ← bare clone (source of truth)

echo "==> Syncing files to ${TARGET_DIR}..."

# Compose file — always copy (this is what docker-update.sh scans)
cp "$CLONE_DIR/server.yml" "$TARGET_DIR/server.yml"

# Build context — must be a subdirectory referenced by server.yml
rsync -a --delete "$CLONE_DIR/dev-container/" "$TARGET_DIR/dev-container/"

# Data directories — only create if missing (preserve existing data)
for d in gitea buildbuddy ssh-keys; do
    mkdir -p "$TARGET_DIR/$d"
done

# Scripts and docs — always copy
for f in setup.sh setup_linux_client.sh SETUP_GUIDE.md .env.example .gitignore; do
    if [[ -f "$CLONE_DIR/$f" ]]; then
        cp "$CLONE_DIR/$f" "$TARGET_DIR/$f"
    fi
done

# .env — never overwrite (contains secrets)
if [[ ! -f "$TARGET_DIR/.env" ]]; then
    if [[ -f "$CLONE_DIR/.env.example" ]]; then
        cp "$CLONE_DIR/.env.example" "$TARGET_DIR/.env"
        echo ""
        echo "  ⚠ Created .env from .env.example — EDIT IT with your API keys:"
        echo "    nano ${TARGET_DIR}/.env"
    fi
else
    echo "  .env already exists — not overwritten (secrets preserved)"
fi

# Make scripts executable
chmod +x "$TARGET_DIR/setup.sh" "$TARGET_DIR/setup_linux_client.sh" 2>/dev/null || true

# ── Copy docker-update.sh if not present ──────────────────────
if [[ ! -f "$TARGET_DIR/docker-update.sh" ]]; then
    echo "  NOTE: docker-update.sh not found in ${TARGET_DIR}/"
    echo "  Copy it there manually or clone the docker-standalone-to-compose repo."
fi

echo ""
echo "==> Deploy complete. Files in ${TARGET_DIR}/:"
ls -1 "$TARGET_DIR"/*.yml "$TARGET_DIR"/*.sh 2>/dev/null || true
echo ""
echo "  To set up for the first time:  cd ${TARGET_DIR} && ./setup.sh"
echo "  To update later:              cd ${TARGET_DIR} && ./docker-update.sh"
