#!/usr/bin/env bash
#
# dng-cleanup.sh
#
# A post-processing tool for Adobe DNG Converter. This script automates the
# cleanup and organization of DNG files after conversion by:
#   1. Restoring file system timestamps from EXIF DateTimeOriginal.
#   2. Verifying and deleting the original redundant DNG files.
#   3. Renaming converted files (e.g., *_1.dng) to standard .DNG format.
#
# Usage:
#   ./dng-cleanup.sh [OPTIONS] [DIRECTORY]
#
# Options:
#   -y, --yes           Wet-run: actually perform all changes (default is dry-run)
#   -r, --recursive     Search subdirectories recursively (default: enabled)
#       --no-recursive  Only process the top-level directory
#   -h, --help          Show this help message
#
# This script defaults to the current working directory if none is specified.
# It requires 'exiftool' to be installed.

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
DRY_RUN=true
RECURSIVE=true
TARGET_DIR="."

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Signal handling ───────────────────────────────────────────────────────────
cleanup() {
  echo
  echo -e "${RED}[INTERRUPTED]${RESET} Script interrupted. No in-progress file operations were left incomplete."
  exit 130
}
trap cleanup INT TERM

# ── Helpers ───────────────────────────────────────────────────────────────────
log_info()    { echo -e "${CYAN}[INFO]${RESET}    $*"; }
log_action()  { echo -e "${GREEN}[ACTION]${RESET}  $*"; }
log_dry()     { echo -e "${YELLOW}[DRY-RUN]${RESET} $*"; }
log_warn()    { echo -e "${RED}[WARN]${RESET}    $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET}   $*"; }
log_skip()    { echo -e "          ${BOLD}SKIP${RESET}    $*"; }

usage() {
  sed -n '2,/^[^#]/p' "$0" | sed 's/^# //;s/^#$//' | head -n -1
  exit 0
}

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)          DRY_RUN=false;   shift ;;
    -r|--recursive)    RECURSIVE=true;  shift ;;
    --no-recursive)    RECURSIVE=false; shift ;;
    -h|--help)         usage ;;
    -*)  echo "Unknown option: $1" >&2; exit 1 ;;
    *)   TARGET_DIR="$1"; shift ;;
  esac
done

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v exiftool &>/dev/null; then
  echo -e "${RED}ERROR:${RESET} exiftool is not installed or not in PATH." >&2
  exit 1
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo -e "${RED}ERROR:${RESET} Directory not found: $TARGET_DIR" >&2
  exit 1
fi

TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"   # absolute path

# ── Banner ────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}=== DNG Cleanup Script ===${RESET}"
echo -e "  Directory : $TARGET_DIR"
echo -e "  Recursive : $RECURSIVE"
if $DRY_RUN; then
  echo -e "  Mode      : ${YELLOW}DRY-RUN (pass -y to apply changes)${RESET}"
else
  echo -e "  Mode      : ${GREEN}WET-RUN (changes will be applied)${RESET}"
fi
echo

# ── Build file list ───────────────────────────────────────────────────────────
if $RECURSIVE; then
  mapfile -d '' CONVERTED_FILES < <(
    find "$TARGET_DIR" -type f \( -name '*_1.dng' -o -name '*_1.DNG' \) -print0 | sort -z
  )
else
  mapfile -d '' CONVERTED_FILES < <(
    find "$TARGET_DIR" -maxdepth 1 -type f \( -name '*_1.dng' -o -name '*_1.DNG' \) -print0 | sort -z
  )
fi

if [[ ${#CONVERTED_FILES[@]} -eq 0 ]]; then
  log_info "No *_1.dng files found in $TARGET_DIR"
  exit 0
fi

log_info "Found ${#CONVERTED_FILES[@]} converted file(s) to process."
echo

# ── Counters & error log ──────────────────────────────────────────────────────
COUNT_OK=0
COUNT_SKIP=0
# Each entry: "path :: reason"
ERROR_REPORT=()

# ── Main loop ─────────────────────────────────────────────────────────────────
for CONV_FILE in "${CONVERTED_FILES[@]}"; do
  DIR="$(dirname "$CONV_FILE")"
  BASENAME="$(basename "$CONV_FILE")"   # e.g. IMG_0042_1.dng

  # Derive stem (strip _1 suffix before extension)
  STEM="${BASENAME%_1.*}"               # IMG_0042
  ORIG_UPPER="$DIR/${STEM}.DNG"
  ORIG_LOWER="$DIR/${STEM}.dng"
  FINAL_FILE="$ORIG_UPPER"             # always rename to uppercase .DNG

  # Which original exists?
  ORIG_FILE=""
  if [[ -f "$ORIG_UPPER" ]]; then
    ORIG_FILE="$ORIG_UPPER"
  elif [[ -f "$ORIG_LOWER" ]]; then
    ORIG_FILE="$ORIG_LOWER"
  fi

  echo -e "${BOLD}── $CONV_FILE${RESET}"

  # ── Guard: empty file check ───────────────────────────────────────────────
  if [[ ! -s "$CONV_FILE" ]]; then
    log_error "File is empty (0 bytes) — skipping, leaving both files untouched."
    ERROR_REPORT+=("$CONV_FILE :: File is empty (0 bytes)")
    (( COUNT_SKIP++ )) || true
    echo
    continue
  fi

  # ── Step 1: Set timestamps ────────────────────────────────────────────────
  echo -n "   [1/3] Set EXIF timestamps  → "
  if $DRY_RUN; then
    log_dry "exiftool \"-FileCreateDate<DateTimeOriginal\" \"-FileModifyDate<DateTimeOriginal\" \"$CONV_FILE\""
  else
    # Capture both stdout and stderr; exiftool exits 0 even on "0 files updated"
    EXIF_OUTPUT="$(exiftool -quiet \
      "-FileCreateDate<DateTimeOriginal" \
      "-FileModifyDate<DateTimeOriginal" \
      "$CONV_FILE" 2>&1)"
    EXIF_EXIT=$?

    # Clean up any exiftool backup file regardless of outcome
    [[ -f "${CONV_FILE}_original" ]] && rm -f "${CONV_FILE}_original"

    if [[ $EXIF_EXIT -ne 0 ]]; then
      MSG="exiftool exited with error (exit $EXIF_EXIT): ${EXIF_OUTPUT}"
      log_error "$MSG — leaving both files untouched."
      ERROR_REPORT+=("$CONV_FILE :: $MSG")
      (( COUNT_SKIP++ )) || true
      echo
      continue
    fi

    # exiftool exits 0 but prints "0 image files updated" when tag is missing
    if echo "$EXIF_OUTPUT" | grep -q "0 image files updated"; then
      MSG="exiftool updated 0 files (DateTimeOriginal tag missing or unreadable)"
      log_error "$MSG — leaving both files untouched."
      ERROR_REPORT+=("$CONV_FILE :: $MSG")
      (( COUNT_SKIP++ )) || true
      echo
      continue
    fi

    log_action "Timestamps updated."
  fi

  # ── Step 2: Delete original .DNG ─────────────────────────────────────────
  echo -n "   [2/3] Delete original DNG  → "
  if [[ -z "$ORIG_FILE" ]]; then
    log_skip "No matching original found (${STEM}.DNG / ${STEM}.dng) — skipping delete."
  elif [[ "$ORIG_FILE" == "$CONV_FILE" ]]; then
    log_warn "Original and converted paths are the same — skipping delete."
  else
    if $DRY_RUN; then
      log_dry "rm \"$ORIG_FILE\""
    else
      # Safety: verify we're not about to delete the same file (inode check)
      ORIG_INODE=$(stat -c %i "$ORIG_FILE" 2>/dev/null || echo "a")
      CONV_INODE=$(stat -c %i "$CONV_FILE" 2>/dev/null || echo "b")
      if [[ "$ORIG_INODE" == "$CONV_INODE" ]]; then
        log_warn "Original and converted point to the same inode — skipping delete."
      else
        rm "$ORIG_FILE"
        log_action "Deleted $ORIG_FILE"
      fi
    fi
  fi

  # ── Step 3: Rename _1.dng → .DNG ─────────────────────────────────────────
  echo -n "   [3/3] Rename to ${STEM}.DNG  → "
  if $DRY_RUN; then
    log_dry "mv \"$CONV_FILE\" \"$FINAL_FILE\""
  else
    mv "$CONV_FILE" "$FINAL_FILE"
    log_action "Renamed to $FINAL_FILE"
  fi

  (( COUNT_OK++ )) || true
  echo
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}=== Summary ===${RESET}"
if $DRY_RUN; then
  echo -e "  ${YELLOW}Dry-run only — no changes were made. Pass -y to apply.${RESET}"
  echo    "  Files that would be processed : $COUNT_OK"
  echo    "  Files that would be skipped   : $COUNT_SKIP"
else
  echo "  Successfully processed : $COUNT_OK"
  echo "  Skipped (errors)       : $COUNT_SKIP"
fi

if [[ ${#ERROR_REPORT[@]} -gt 0 ]]; then
  echo
  echo -e "${RED}${BOLD}=== Errors — the following files were left untouched ===${RESET}"
  for ENTRY in "${ERROR_REPORT[@]}"; do
    FILE="${ENTRY%% ::*}"
    REASON="${ENTRY#*:: }"
    echo -e "  ${RED}✗${RESET} $FILE"
    echo    "      Reason: $REASON"
  done
fi

echo
