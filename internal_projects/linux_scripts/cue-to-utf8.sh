#!/usr/bin/env bash

#
# cue-to-utf8.sh
#
# Batch converts .cue sheet files from their detected character encoding to UTF-8.
# Useful for fixing character encoding issues in music metadata on Linux.
#
# Usage: ./cue-to-utf8.sh [directory]
# Default: current directory

set -euo pipefail

usage() {
    sed -n '2,/^[^#]/p' "$0" | sed 's/^# //;s/^#$//' | head -n -1
    exit 0
}

# ── Argument parsing ──────────────────────────────────────────────────────────
ROOT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *)  ROOT_DIR="$1"; shift ;;
    esac
done

ROOT_DIR="${ROOT_DIR:-.}"

if [[ ! -d "$ROOT_DIR" ]]; then
    echo "Error: directory not found: $ROOT_DIR" >&2
    exit 1
fi

# Check if uchardet and iconv are available
if ! command -v uchardet >/dev/null 2>&1; then
    echo "Error: uchardet not found. Install it first." >&2
    echo "  Ubuntu/Debian : sudo apt install uchardet" >&2
    echo "  macOS         : brew install uchardet" >&2
    exit 1
fi

if ! command -v iconv >/dev/null 2>&1; then
    echo "Error: iconv not found. It's part of coreutils." >&2
    exit 1
fi

# Counter
converted=0
skipped=0
failed=0

echo "Scanning for .cue files in: $ROOT_DIR"
echo "----------------------------------------"

# NOTE: Using process substitution (< <(find ...)) instead of a pipe
# (find | while) to avoid the subshell variable-scope bug.  With a pipe,
# the while loop runs in a subshell and counter increments are lost.
while IFS= read -r -d '' file; do
    # Detect encoding
    encoding=$(uchardet "$file" 2>/dev/null || true)

    if [[ -z "$encoding" ]]; then
        echo "WARN: $file → uchardet returned empty result, skipping"
        (( failed++ )) || true
        continue
    fi

    # Skip if already UTF-8
    if [[ "$encoding" == "UTF-8" || "$encoding" == "ASCII" ]]; then
        echo "SKIP: $file → already $encoding"
        (( skipped++ )) || true
        continue
    fi

    # Create backup
    backup="${file}.bak.$(date +%Y%m%d-%H%M%S)"
    if ! cp "$file" "$backup"; then
        echo "FAILED: $file → could not create backup, skipping"
        (( failed++ )) || true
        continue
    fi

    # Convert to UTF-8 (iconv will fail gracefully if invalid)
    if iconv -f "$encoding" -t UTF-8 "$backup" -o "$file" 2>/dev/null; then
        echo "CONVERTED: $file → $encoding → UTF-8 (backup: $(basename "$backup"))"
        (( converted++ )) || true
    else
        echo "FAILED: $file → invalid $encoding data, restored from backup"
        mv "$backup" "$file"  # restore original
        (( failed++ )) || true
    fi
done < <(find "$ROOT_DIR" -type f -name "*.cue" -print0)

echo "----------------------------------------"
echo "Done: $converted converted, $skipped already UTF-8, $failed failed"
