#!/usr/bin/env bash
#
# verify-exif-timestamps.sh
#
# Audits media files for timestamp discrepancies between file system metadata
# and embedded EXIF data. Generates a per-directory summary of:
#   - Timestamp mismatches exceeding a threshold.
#   - Files missing EXIF temporal metadata.
#
# Requirements: exiftool (https://exiftool.org/)
#
# Usage:
#   ./verify-exif-timestamps.sh [directory] [options]
#
# Options:
#   -d <seconds>    Mismatch threshold in seconds (default: 86400 = 1 day)
#   --fix           Dry run: show exact timestamp changes without applying them
#   --fix-wet-run   Apply the timestamp changes for real
#   -h, --help      Show this help message

# NOTE: intentionally NO set -e; arithmetic (( )) returns 1 for false and
# would kill the script. All errors are handled explicitly instead.
set -uo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
SEARCH_DIR="."
THRESHOLD=86400
FIX_MODE=false
WET_RUN=false

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

usage() {
  sed -n '2,/^[^#]/p' "$0" | sed 's/^# //;s/^#$//' | head -n -1
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) THRESHOLD="$2"; shift 2 ;;
    --fix) FIX_MODE=true; shift ;;
    --fix-wet-run) FIX_MODE=true; WET_RUN=true; shift ;;
    -h|--help) usage ;;
    -*) echo "Unknown option: $1"; exit 1 ;;
    *)  SEARCH_DIR="$1"; shift ;;
  esac
done

if ! command -v exiftool &>/dev/null; then
  echo -e "${RED}Error: exiftool is not installed.${NC}"
  echo "  Ubuntu/Debian : sudo apt install libimage-exiftool-perl"
  echo "  macOS         : brew install exiftool"
  exit 1
fi
if [[ ! -d "$SEARCH_DIR" ]]; then
  echo "Error: '$SEARCH_DIR' not found."
  exit 1
fi

# ── Extension filter ──────────────────────────────────────────────────────────
PHOTO_EXTS="jpg jpeg png tiff tif heic heif raw cr2 cr3 nef nrw arw orf rw2 dng pef srw"
VIDEO_EXTS="mp4 mov avi mkv m4v 3gp mts m2ts wmv flv webm mpg mpeg"



# ── EXIF date -> epoch ────────────────────────────────────────────────────────
exif_to_epoch() {
  local raw="$1"
  # Normalise EXIF date separators: "2015:09:20 20:14:08" -> "2015-09-20 20:14:08"
  local n
  n=$(echo "$raw" | sed 's/^\([0-9]\{4\}\):\([0-9]\{2\}\):\([0-9]\{2\}\)/\1-\2-\3/')
  # Try GNU date (honours timezone offset natively)
  date -d "$n" +%s 2>/dev/null && return
  # BSD date: strip timezone offset (+HH:MM or -HH:MM) then parse
  local stripped
  stripped=$(echo "$n" | sed 's/[+-][0-9]\{2\}:[0-9]\{2\}$//')
  date -j -f "%Y-%m-%d %H:%M:%S" "$stripped" +%s 2>/dev/null || true
}

# ── Temp workspace ────────────────────────────────────────────────────────────
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

# Per-directory data lives in $TMPDIR_WORK/<safe_name>/
#   path            - the actual directory path
#   total           - count of all media files
#   mismatch_count  - count of timestamp mismatches
#   noexif_count    - count of files with no EXIF date
#   mismatch_ex     - up to 3 example basenames
#   noexif_ex       - up to 3 example basenames

# Convert a directory path to a safe flat name for use as a folder name
dir_key() {
  # Replace non-alphanumeric chars with underscores, then append a short hash
  local safe hash
  safe=$(echo "$1" | tr -cs 'a-zA-Z0-9' '_')
  if command -v md5sum &>/dev/null; then
    hash=$(echo -n "$1" | md5sum | cut -c1-8)
  else
    hash=$(echo -n "$1" | md5 | cut -c1-8)
  fi
  echo "${safe:0:40}_${hash}"
}

# Increment an integer stored in a file
inc_file() {
  local f="$1"
  local n=0
  if [[ -s "$f" ]]; then
    n=$(cat "$f")
  fi
  echo $(( n + 1 )) > "$f"
}

# Append a basename to an examples file (max 3 lines)
add_example() {
  local f="$1" val="$2"
  local cnt=0
  if [[ -s "$f" ]]; then
    cnt=$(wc -l < "$f")
  fi
  if [[ $cnt -lt 3 ]]; then
    echo "$val" >> "$f"
  fi
}

# Ensure all per-dir files exist and record a total hit
init_dir() {
  local dir="$1"
  local key d
  key=$(dir_key "$dir")
  d="$TMPDIR_WORK/$key"
  if [[ ! -d "$d" ]]; then
    mkdir -p "$d"
    echo "$dir" > "$d/path"
    echo 0 > "$d/total"
    echo 0 > "$d/mismatch_count"
    echo 0 > "$d/noexif_count"
    touch "$d/mismatch_ex" "$d/noexif_ex"
    echo "$key" >> "$TMPDIR_WORK/dirs_seen"
  fi
  inc_file "$d/total"
  echo "$d"   # return the dir path
}

# ── Master dir-seen list ──────────────────────────────────────────────────────
touch "$TMPDIR_WORK/dirs_seen"

# ── Helper: format EXIF date for display ──────────────────────────────────────
fmt_date() {
  echo "$1" | sed 's/^\([0-9]\{4\}\):\([0-9]\{2\}\):\([0-9]\{2\}\)/\1-\2-\3/'
}

# ── Build find arguments safely (no eval) ─────────────────────────────────────
FIND_ARGS=()
_FIND_FIRST=true
for _ext in $PHOTO_EXTS $VIDEO_EXTS; do
  if $_FIND_FIRST; then
    FIND_ARGS+=(-iname "*.${_ext}")
    _FIND_FIRST=false
  else
    FIND_ARGS+=(-o -iname "*.${_ext}")
  fi
done

# ── Scan ──────────────────────────────────────────────────────────────────────
total=0
echo -e "${CYAN}Scanning ${SEARCH_DIR} …${NC}"

while IFS= read -r -d '' file; do
  base=$(basename "$file")

  # Skip macOS/Bridge sidecar files (._filename)
  [[ "$base" == ._* ]] && continue

  total=$(( total + 1 ))
  dir=$(dirname "$file")

  d=$(init_dir "$dir")

  # ── Filesystem mtime (epoch + human) ──
  fs_epoch=""
  fs_date=""
  if stat --version &>/dev/null 2>&1; then
    # GNU stat
    fs_epoch=$(stat -c %Y "$file" 2>/dev/null || true)
    fs_date=$(stat -c %y  "$file" 2>/dev/null | cut -d'.' -f1 || true)
  else
    # BSD stat — prefer birth time, fall back to mtime
    fs_epoch=$(stat -f %B "$file" 2>/dev/null \
               || stat -f %m "$file" 2>/dev/null \
               || true)
    fs_date=$(stat -f "%SB" -t "%Y-%m-%d %H:%M:%S" "$file" 2>/dev/null \
              || stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$file" 2>/dev/null \
              || true)
  fi
  if [[ -z "$fs_epoch" ]]; then
    continue
  fi

  # ── EXIF date ──
  exif_raw=$(exiftool -m \
    -DateTimeOriginal -CreateDate -MediaCreateDate -TrackCreateDate \
    -QuickTime:CreateDate -QuickTime:ModifyDate \
    -s3 "$file" 2>/dev/null | head -1 || true)

  if [[ -z "$exif_raw" || "$exif_raw" == "0000:00:00 00:00:00" ]]; then
    inc_file "$d/noexif_count"
    add_example "$d/noexif_ex" "${base}	fs:${fs_date}"
    continue
  fi

  exif_epoch=$(exif_to_epoch "$exif_raw")
  if [[ -z "$exif_epoch" ]]; then
    inc_file "$d/noexif_count"
    add_example "$d/noexif_ex" "${base}	fs:${fs_date}"
    continue
  fi

  # ── Compare ──
  diff_sec=$(( fs_epoch - exif_epoch ))
  if [[ $diff_sec -lt 0 ]]; then
    diff_sec=$(( -diff_sec ))
  fi
  if [[ $diff_sec -gt $THRESHOLD ]]; then
    inc_file "$d/mismatch_count"
    # Normalise exif_raw to use dashes for display
    exif_display=$(fmt_date "$exif_raw")
    add_example "$d/mismatch_ex" "${base}	fs:${fs_date}	exif:${exif_display}	path:${file}"
    echo "$file" >> "$d/mismatch_files"
  fi

done < <(find "$SEARCH_DIR" -type f \( "${FIND_ARGS[@]}" \) -print0 2>/dev/null)

# ── Print summary ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  SUMMARY  (threshold: ${THRESHOLD}s / $(( THRESHOLD / 3600 ))h)${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "  Total files scanned: ${total}"
echo ""

has_issues=false

while IFS= read -r key; do
  [[ -z "$key" ]] && continue
  d="$TMPDIR_WORK/$key"
  [[ ! -d "$d" ]] && continue

  dir=$(cat "$d/path")
  dtotal=$(cat "$d/total")
  mm=$(cat "$d/mismatch_count")
  ne=$(cat "$d/noexif_count")

  if [[ $mm -eq 0 && $ne -eq 0 ]]; then
    continue
  fi
  has_issues=true

  # ── Directory header with inline counts ──
  counts=""
  [[ $mm -gt 0 ]] && counts="${RED}mismatch:${mm}${NC}"
  [[ $mm -gt 0 && $ne -gt 0 ]] && counts="${counts}  "
  [[ $ne -gt 0 ]] && counts="${counts}${YELLOW}no-exif:${ne}${NC}"
  echo -e "${BOLD}📁 ${dir}${NC}  [${dtotal} files]  ${counts}"

  if [[ $mm -gt 0 ]]; then
    while IFS=$'\t' read -r name fs_ts exif_ts _path; do
      [[ -z "$name" ]] && continue
      echo "   • ${name}  fs:${fs_ts#fs:}  exif:${exif_ts#exif:}"
    done < "$d/mismatch_ex"
  fi

  if [[ $ne -gt 0 ]]; then
    while IFS=$'\t' read -r name fs_ts; do
      [[ -z "$name" ]] && continue
      echo "   • ${name}  fs:${fs_ts#fs:}"
    done < "$d/noexif_ex"
  fi

done < "$TMPDIR_WORK/dirs_seen"

if [[ "$has_issues" == "false" ]]; then
  echo -e "  ${CYAN}No mismatches or missing EXIF dates found.${NC}"
fi
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"

# ── Fix mode ──────────────────────────────────────────────────────────────────
if [[ "$FIX_MODE" == "true" ]]; then
  echo ""
  if [[ "$WET_RUN" == "true" ]]; then
    echo -e "${BOLD}  FIX (wet run): applying changes …${NC}"
  else
    echo -e "${BOLD}  FIX (dry run): showing planned changes — re-run with --fix-wet-run to apply${NC}"
  fi
  echo ""

  fixed=0; failed=0

  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    d="$TMPDIR_WORK/$key"
    mf="$d/mismatch_files"
    [[ ! -s "$mf" ]] && continue

    while IFS= read -r fpath; do
      [[ -z "$fpath" ]] && continue

      # ── Resolve the create timestamp to use ──
      create_raw=$(exiftool -m \
        -DateTimeOriginal -CreateDate -QuickTime:CreateDate \
        -s3 "$fpath" 2>/dev/null | head -1 || true)

      # ── Resolve the modify timestamp to use ──
      modify_raw=$(exiftool -m \
        -ModifyDate -QuickTime:ModifyDate \
        -s3 "$fpath" 2>/dev/null | head -1 || true)

      # Normalise for display
      create_display=$(fmt_date "$create_raw")
      if [[ -n "$modify_raw" && "$modify_raw" != "0000:00:00 00:00:00" ]]; then
        modify_display=$(fmt_date "$modify_raw")
        use_modify_for_mtime=true
      else
        modify_display="$create_display  (no modify date in metadata, using create date)"
        use_modify_for_mtime=false
      fi

      # ── Get current fs timestamps for comparison ──
      if stat --version &>/dev/null 2>&1; then
        cur_create=$(stat -c %y "$fpath" 2>/dev/null | cut -d'.' -f1 || true)
        cur_modify=$(stat -c %y "$fpath" 2>/dev/null | cut -d'.' -f1 || true)
      else
        cur_create=$(stat -f "%SB" -t "%Y-%m-%d %H:%M:%S" "$fpath" 2>/dev/null || true)
        cur_modify=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$fpath" 2>/dev/null || true)
      fi

      echo -e "  ${BOLD}$(basename "$fpath")${NC}"
      echo    "    FileCreateDate : ${cur_create}  →  ${create_display}"
      echo    "    FileModifyDate : ${cur_modify}  →  ${modify_display}"

      if [[ "$WET_RUN" == "true" ]]; then
        if [[ "$use_modify_for_mtime" == "true" ]]; then
          exiftool_args=(
            -m -overwrite_original
            "-FileCreateDate<DateTimeOriginal"
            "-FileCreateDate<CreateDate"
            "-FileCreateDate<QuickTime:CreateDate"
            "-FileModifyDate<ModifyDate"
            "-FileModifyDate<QuickTime:ModifyDate"
          )
        else
          exiftool_args=(
            -m -overwrite_original
            "-FileCreateDate<DateTimeOriginal"
            "-FileCreateDate<CreateDate"
            "-FileCreateDate<QuickTime:CreateDate"
            "-FileModifyDate<DateTimeOriginal"
            "-FileModifyDate<CreateDate"
            "-FileModifyDate<QuickTime:CreateDate"
          )
        fi

        if exiftool "${exiftool_args[@]}" "$fpath" &>/dev/null; then
          echo -e "    ${GREEN}✓ applied${NC}"
          fixed=$(( fixed + 1 ))
        else
          echo -e "    ${RED}✗ failed${NC}"
          failed=$(( failed + 1 ))
        fi
      fi

      echo ""
    done < "$mf"
  done < "$TMPDIR_WORK/dirs_seen"

  if [[ "$WET_RUN" == "true" ]]; then
    echo -e "  Fixed : ${GREEN}${fixed}${NC}  Failed : ${RED}${failed}${NC}"
  fi
  echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
fi
