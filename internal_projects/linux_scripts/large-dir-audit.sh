#!/usr/bin/env bash
#
# large-dir-audit.sh
#
# Identifies large directories by auditing the size of files contained directly
# within them (non-recursively). Helps locate bloated directories quickly.
#
# Usage: ./large-dir-audit.sh [directory] [threshold_gb]
#   directory      Directory to scan (default: current directory)
#   threshold_gb   Minimum size in GB to report (default: 100)
#
# Options:
#   -h, --help     Show this help message

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
SEARCH_DIR=""
THRESHOLD_GB=""

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            sed -n '2,/^[^#]/p' "$0" | sed 's/^# //;s/^#$//' | head -n -1
            exit 0
            ;;
        *)
            if [[ -z "$SEARCH_DIR" ]]; then
                SEARCH_DIR="$arg"
            elif [[ -z "$THRESHOLD_GB" ]]; then
                THRESHOLD_GB="$arg"
            else
                echo "Error: unexpected argument: $arg" >&2
                echo "Usage: $0 [directory] [threshold_gb]" >&2
                exit 1
            fi
            ;;
    esac
done

SEARCH_DIR="${SEARCH_DIR:-.}"
THRESHOLD_GB="${THRESHOLD_GB:-100}"

# ── Input validation ─────────────────────────────────────────────────────────
if [[ ! -d "$SEARCH_DIR" ]]; then
    echo "Error: directory not found: $SEARCH_DIR" >&2
    exit 1
fi

if ! [[ "$THRESHOLD_GB" =~ ^[0-9]+$ ]] || [[ "$THRESHOLD_GB" -le 0 ]]; then
    echo "Error: threshold must be a positive integer (got: $THRESHOLD_GB)" >&2
    exit 1
fi

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v bc &>/dev/null; then
    echo "Error: bc is required but not installed." >&2
    echo "  Install: sudo apt-get install bc" >&2
    exit 1
fi

THRESHOLD_KB=$((THRESHOLD_GB * 1024 * 1024))

echo "Scanning directories in: $SEARCH_DIR"
echo "Threshold: ${THRESHOLD_GB}GB (direct files only)"
echo "-------------------------------------------"

found=0

while IFS= read -r -d '' dir; do
    # Sum sizes of direct child files only (maxdepth 1)
    size_kb=$(find "$dir" -maxdepth 1 -type f -printf "%s\n" 2>/dev/null \
              | awk '{sum += $1} END {print int(sum/1024)}')

    size_kb=${size_kb:-0}

    if [[ "$size_kb" -ge "$THRESHOLD_KB" ]]; then
        size_gb=$(echo "scale=2; $size_kb / 1024 / 1024" | bc)
        printf "%-80s %s GB\n" "$dir" "$size_gb"
        (( found++ )) || true
    fi
done < <(find "$SEARCH_DIR" -type d -print0)

echo "-------------------------------------------"
echo "Found $found directories exceeding ${THRESHOLD_GB}GB."
