#!/bin/bash
# docker-compose-update.sh
# Pulls latest images and recreates containers for all Docker Compose projects
# in the same directory. Each .yml file is treated as a separate project.
#
# Usage: ./docker-compose-update.sh [options] [project_names...]
#   --force, -f         Force recreate all containers even if no image changed
#   --build SERVICE     Build SERVICE with --no-cache and recreate with --force-recreate
#   project_names       Optional: only update specific projects (e.g., 'ddns' or 'ddns.yml')
# Requirements: Docker with Compose plugin (docker compose), bash 4+

set -uo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")" && pwd)"
FORCE=false
BUILD_SERVICE=""
TARGETS=()
SUCCESS=()
FAILED=()

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f)      FORCE=true; shift ;;
    --build)         [[ $# -lt 2 || "$2" == -* ]] && { echo "ERROR: --build requires a service name" >&2; exit 1; }; BUILD_SERVICE="$2"; shift 2 ;;
    --build=*)       BUILD_SERVICE="${1#*=}"; shift ;;
    -*)              echo "Unknown option: $1" >&2; exit 1 ;;
    *)               TARGETS+=("$1"); shift ;;
  esac
done

# Check dependencies
if ! command -v docker &>/dev/null; then
  echo "ERROR: docker is not installed or not in PATH" >&2
  exit 1
fi
if ! docker compose version &>/dev/null; then
  echo "ERROR: docker compose plugin is not available" >&2
  exit 1
fi

# Determine which yml files to process
shopt -s nullglob
yml_files=()
if [[ ${#TARGETS[@]} -eq 0 ]]; then
  yml_files=("$COMPOSE_DIR"/*.yml)
else
  for t in "${TARGETS[@]}"; do
    f="$COMPOSE_DIR/$t"
    [[ "$f" != *.yml ]] && f="${f}.yml"
    if [[ -f "$f" ]]; then
      yml_files+=("$f")
    else
      echo "ERROR: Compose file not found for '$t' (tried $f)" >&2
      exit 1
    fi
  done
fi

if [[ ${#yml_files[@]} -eq 0 ]]; then
  echo "No .yml files found to process."
  exit 0
fi

force_remove_conflicting() {
  local container_name="$1"
  local max_attempts=5
  local attempt=0

  while docker ps -a --format '{{.Names}}' | grep -qx "$container_name"; do
    attempt=$((attempt + 1))
    if [[ $attempt -gt $max_attempts ]]; then
      echo "    ERROR: Could not remove $container_name after $max_attempts attempts" >&2
      return 1
    fi
    echo "    Stopping and removing conflicting container: $container_name (attempt $attempt)"
    docker stop "$container_name" 2>/dev/null || true
    docker rm -f "$container_name" 2>/dev/null || true
    sleep 1
  done
}

compose_up() {
  local project="$1"
  local f="$2"
  shift 2
  # Use any extra arguments passed (like service names or --force-recreate)
  local up_args=(docker compose -p "$project" -f "$f" up -d --remove-orphans "$@")
  [[ "$FORCE" == "true" ]] && up_args+=(--force-recreate)

  local output exit_code
  local max_retries=3 retry=0

  while [[ $retry -le $max_retries ]]; do
    output=$("${up_args[@]}" 2>&1)
    exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
      echo "$output"
      return 0
    fi

    if echo "$output" | grep -q "The container name"; then
      local container_names
      container_names=$(echo "$output" | grep -oP 'The container name "/\K[^"]+' | sort -u)
      if [[ -n "$container_names" ]]; then
        local remove_failed=false
        while IFS= read -r cname; do
          [[ -n "$cname" ]] && force_remove_conflicting "$cname" || remove_failed=true
        done <<< "$container_names"
        [[ "$remove_failed" == "false" ]] && { retry=$((retry + 1)); continue; }
      fi
    fi

    echo "$output" >&2
    return $exit_code
  done

  echo "    ERROR: Failed to bring up $project after $max_retries retries" >&2
  return 1
}

build_service() {
  local project="$1"
  local f="$2"
  local service="$3"

  echo ""
  echo "==> [$project] Building service '$service' (no cache)..."
  if ! docker compose -p "$project" -f "$f" build --no-cache "$service"; then
    echo "==> [$project] Build failed for service '$service'" >&2
    return 1
  fi

  echo "==> [$project] Recreating service '$service'..."
  # Use the robust compose_up function for the deployment
  if ! compose_up "$project" "$f" --force-recreate "$service"; then
    echo "==> [$project] Recreate failed for service '$service'" >&2
    return 1
  fi
  echo "==> [$project] Service '$service' updated."
  return 0
}

update_project() {
  local f="$1"
  local project
  project=$(basename "$f" .yml)

  if [[ -n "$BUILD_SERVICE" ]]; then
    # Skip compose files that don't define this service
    if ! docker compose -p "$project" -f "$f" config --services 2>/dev/null | grep -qx "$BUILD_SERVICE"; then
      echo "==> [$project] Service '$BUILD_SERVICE' not found — skipping"
      return 0
    fi
    build_service "$project" "$f" "$BUILD_SERVICE"
    return $?
  fi

  echo ""
  echo "==> [$project] Pulling latest images..."
  if ! docker compose -p "$project" -f "$f" pull; then
    echo "==> [$project] Pull failed, skipping update" >&2
    return 1
  fi

  echo "==> [$project] Bringing up containers..."
  compose_up "$project" "$f"
}

for f in "${yml_files[@]}"; do
  project=$(basename "$f" .yml)
  if update_project "$f"; then
    SUCCESS+=("$project")
  else
    echo "ERROR: Failed to update $project" >&2
    FAILED+=("$project")
  fi
done

echo ""
echo "==============================="
echo " Update Summary"
echo "==============================="
echo " Success: ${#SUCCESS[@]}"
for p in "${SUCCESS[@]}"; do echo "   ✔ $p"; done
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo " Failed:  ${#FAILED[@]}"
  for p in "${FAILED[@]}"; do echo "   ✘ $p"; done
  exit 1
fi
echo "==============================="