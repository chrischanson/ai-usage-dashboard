#!/usr/bin/env bash

#
# organize-by-date.sh
#
# Automatically organizes files into a YYYY/MM/DD directory structure.
# Prioritizes EXIF 'DateTimeOriginal' for photos/videos, falling back to
# file system modification time (mtime).
#
# Usage: ./organize-by-date.sh <destination_root> [--wet-run]

set -euo pipefail

DEST_ROOT=""
WET_RUN=false

usage() {
    sed -n '2,/^[^#]/p' "$0" | sed 's/^# //;s/^#$//' | head -n -1
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --wet-run) WET_RUN=true ;;
        --help|-h) usage ;;
        *)
            if [[ -z "$DEST_ROOT" ]]; then
                DEST_ROOT="$arg"
            else
                echo "Unknown argument: $arg" >&2
                usage
            fi
            ;;
    esac
done

[[ -z "$DEST_ROOT" ]] && usage

# ── Validate destination ──────────────────────────────────────────────────────
if $WET_RUN; then
    if [[ ! -d "$DEST_ROOT" ]]; then
        echo "Error: destination directory not found: $DEST_ROOT" >&2
        echo "  Create it first, or check the path." >&2
        exit 1
    fi
    if [[ ! -w "$DEST_ROOT" ]]; then
        echo "Error: destination directory is not writable: $DEST_ROOT" >&2
        exit 1
    fi
    echo "==> WET RUN — changes will be applied"
else
    echo "==> DRY RUN — no changes will be made (pass --wet-run to apply)"
fi
echo ""

moved=0
skipped_exists=0
failed=0

get_date_path() {
    local file="$1"

    # 1. Try EXIF DateTimeOriginal (most accurate for photos/videos captured date)
    if command -v exiftool &>/dev/null; then
        local exif_date
        exif_date=$(exiftool -d '%Y/%m/%d' -DateTimeOriginal -S -s "$file" 2>/dev/null || true)
        if [[ "$exif_date" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]]; then
            echo "$exif_date"
            return
        fi
    fi

    # 2. Use mtime — this is what `ls -l` shows and is reliable on all filesystems
    #    including SMB/NFS shares where birth time (%W) is typically 0 or wrong.
    local mtime
    mtime=$(stat -c '%Y' "$file" 2>/dev/null || true)
    if [[ -z "$mtime" ]]; then
        echo ""
        return 1
    fi
    date -d "@${mtime}" '+%Y/%m/%d'
}

while IFS= read -r -d '' file; do
    rel="${file#./}"
    filename="$(basename "$rel")"

    # Skip pseudo/hidden files: names starting with _ or .
    if [[ "$filename" == _* || "$filename" == .* ]]; then
        continue
    fi

    date_path=$(get_date_path "$file" || true)
    if [[ -z "$date_path" ]]; then
        echo "  FAIL (no date) $rel"
        (( failed++ )) || true
        continue
    fi
    dest_dir="${DEST_ROOT}/${date_path}"
    dest_file="${dest_dir}/${filename}"

    if [[ -e "$dest_file" ]]; then
        echo "  SKIP (exists)  $rel  →  $dest_file"
        (( skipped_exists++ )) || true
        continue
    fi

    echo "  MOVE  $rel  →  $dest_file"

    if $WET_RUN; then
        if ! mkdir -p "$dest_dir"; then
            echo "  FAIL (mkdir)   $rel  →  $dest_dir"
            (( failed++ )) || true
            continue
        fi
        if ! mv "$file" "$dest_file"; then
            echo "  FAIL (mv)      $rel  →  $dest_file"
            (( failed++ )) || true
            continue
        fi
    fi

    (( moved++ )) || true

done < <(find . -maxdepth 10 -type f -print0)

echo ""
echo "Summary:"
printf "  To move : %d\n" "$moved"
printf "  Skipped (destination exists) : %d\n" "$skipped_exists"
printf "  Failed  : %d\n" "$failed"
if ! $WET_RUN; then
    echo ""
    echo "  This was a DRY RUN. Re-run with --wet-run to apply."
fi

# Exit with error if there were failures
if [[ $failed -gt 0 ]]; then
    exit 1
fi
