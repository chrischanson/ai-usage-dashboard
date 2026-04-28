#!/usr/bin/env bash
# deploy.sh
# Deploys the linux_dev_server project to the CURRENT directory.
#
# Clones (or pulls) the repo from Gitea, then syncs the project files
# into the current directory alongside other compose stacks.
#
# On each run, this script first checks for an updated version of itself
# from the repo. If a newer deploy.sh is found, it re-executes itself
# with the updated copy.
#
# The dev-container/ subdirectory is preserved (needed for image builds),
# but the compose file (server.yml) sits at the top level so docker-update.sh
# discovers it alongside other .yml stacks.
#
# Usage:
#   cd ~/dev-services && ./deploy.sh
#
# Prerequisites: git, rsync, access to Gitea at localhost:3000
set -euo pipefail

TARGET_DIR="$(pwd)"
GITEA_URL="http://10.0.0.201:3000"
REPO_REMOTE="${GITEA_URL}/admin/projects.git"
REPO_SUBDIR="projects/linux_dev_server"
CLONE_DIR="${TARGET_DIR}/.repos/projects"

# ── Self-update ───────────────────────────────────────────────
# Pull the latest repo first, then check if deploy.sh itself changed.
# If it did, replace ourselves and re-exec so the rest of the script
# runs with the newest logic.
self_update() {
    local self="$TARGET_DIR/deploy.sh"
    local repo_copy="$CLONE_DIR/$REPO_SUBDIR/deploy.sh"

    if [[ ! -f "$repo_copy" ]]; then
        return 0  # No deploy.sh in repo yet — skip
    fi

    if ! cmp -s "$self" "$repo_copy"; then
        echo "==> deploy.sh has been updated — restarting with new version..."
        cp "$repo_copy" "$self"
        chmod +x "$self"
        exec "$self" "$@"
    fi
}

# ── Ensure target directory exists ────────────────────────────
mkdir -p "$TARGET_DIR"

# ── Clone or pull the repo ────────────────────────────────────
# We do NOT use set -e for this section so that a failed pull still
# allows self-update to run from an existing clone.
if [[ -d "$CLONE_DIR/.git" ]]; then
    echo "==> Pulling latest changes..."
    git -C "$CLONE_DIR" sparse-checkout set "$REPO_SUBDIR" "projects/docker-standalone-to-compose"
    git -C "$CLONE_DIR" pull --ff-only || {
        echo "  WARNING: git pull failed — using existing clone"
    }
else
    echo "==> Cloning ${REPO_REMOTE} (sparse: ${REPO_SUBDIR})..."
    mkdir -p "$(dirname "$CLONE_DIR")"
    if ! git clone --filter=blob:none --no-checkout "$REPO_REMOTE" "$CLONE_DIR"; then
        echo "  ERROR: git clone failed. Check REPO_REMOTE and network." >&2
        echo "  REPO_REMOTE=${REPO_REMOTE}" >&2
        exit 1
    fi
    git -C "$CLONE_DIR" sparse-checkout init --cone
    git -C "$CLONE_DIR" sparse-checkout set "$REPO_SUBDIR" "projects/docker-standalone-to-compose"
    git -C "$CLONE_DIR" checkout
fi

# ── Check for self-update (after pull, before sync) ───────────
self_update "$@"

# ── Sync files into target directory ──────────────────────────
# Structure on host (current directory):
#   ./
#     server.yml              ← compose file (top-level for docker-update.sh)
#     deploy.sh               ← this script (self-updating)
#     .env                    ← secrets (never overwritten if it exists)
#     .env.example            ← template
#     .gitignore
#     docker-update.sh        ← shared update script
#     dev-container/          ← build context for the dev service
#     gitea/                  ← persistent data
#     buildbuddy/             ← persistent data
#     ssh-keys/               ← client public keys
#     .repos/projects/         ← sparse clone (source of truth)

echo "==> Syncing files to ${TARGET_DIR}..."

# Compose file — always copy (this is what docker-update.sh scans)
cp "$CLONE_DIR/$REPO_SUBDIR/server.yml" "$TARGET_DIR/server.yml"

# Build context — must be a subdirectory referenced by server.yml
rsync -a --delete "$CLONE_DIR/$REPO_SUBDIR/dev-container/" "$TARGET_DIR/dev-container/"

# Data directories — only create if missing (preserve existing data)
for d in gitea buildbuddy ssh-keys; do
    mkdir -p "$TARGET_DIR/$d"
done

# Scripts and docs — always copy
for f in .env.example .gitignore; do
    if [[ -f "$CLONE_DIR/$REPO_SUBDIR/$f" ]]; then
        cp "$CLONE_DIR/$REPO_SUBDIR/$f" "$TARGET_DIR/$f"
    fi
done

# .env — never overwrite (contains secrets)
if [[ ! -f "$TARGET_DIR/.env" ]]; then
    if [[ -f "$CLONE_DIR/$REPO_SUBDIR/.env.example" ]]; then
        cp "$CLONE_DIR/$REPO_SUBDIR/.env.example" "$TARGET_DIR/.env"
        echo ""
        echo "  ⚠ Created .env from .env.example — EDIT IT with your API keys:"
        echo "    nano ${TARGET_DIR}/.env"
    fi
else
    echo "  .env already exists — not overwritten (secrets preserved)"
fi



# ── Copy docker-update.sh ──────────────────────
if [[ -f "$CLONE_DIR/projects/docker-standalone-to-compose/docker-update.sh" ]]; then
    cp "$CLONE_DIR/projects/docker-standalone-to-compose/docker-update.sh" "$TARGET_DIR/docker-update.sh"
    chmod +x "$TARGET_DIR/docker-update.sh"
else
    if [[ ! -f "$TARGET_DIR/docker-update.sh" ]]; then
        echo "  NOTE: docker-update.sh not found in ${TARGET_DIR}/"
        echo "  Copy it there manually or clone the docker-standalone-to-compose repo."
    fi
fi

echo ""
echo "==> Deploy complete. Files in ${TARGET_DIR}/:"
ls -1 "$TARGET_DIR"/*.yml "$TARGET_DIR"/*.sh 2>/dev/null || true
echo ""
echo "  To rebuild dev container:      ./docker-update.sh --build dev"
echo "  To update all services:        ./docker-update.sh"
