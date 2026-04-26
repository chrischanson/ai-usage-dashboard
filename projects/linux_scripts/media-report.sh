#!/usr/bin/env bash
#
# media-report.sh
#
# A comprehensive media inventory tool. Scans directories recursively and
# generates a report on file counts and total sizes grouped by subdirectory.
# Categorizes media (DNG, RAW, JPEG, Video) using EXIF metadata.
#
# Includes an optional DNG compression workflow using 'tinydng-cli'.
#
# ── Compression Workflow ──────────────────────────────────────────────────────
# --compress            Generate tinydng-cli commands for uncompressed DNGs.
#                       Prints commands; use --wet-run to execute.
#
# --effort <1-10>       Encoder effort level (default: 5).
#                       Higher = smaller file, but slower.
#
# --sub-folder          Save output files to an "output" subfolder (default).
#                       Files named: originalname_effort_N.dng.
#
# --no-sub-folder       Write output files in-place (via temp file swap).
#
# --replace             Replace originals with compressed files from "output/".
#                       Run after --compress --wet-run has finished successfully.
#
# --wet-run             Execute the generated commands.
#
# Requirements:
#   - exiftool
#   - tinydng-cli (required for --compress)
#
# Usage:
#   ./media-report.sh [OPTIONS] [DIRECTORY]
#
# Options:
#   --compress            Enable DNG compression workflow
#   --effort <N>          Encoder effort 1-10 (default: 5)
#   --sub-folder          Save to "output/" subfolder (default)
#   --no-sub-folder       Write output files in-place
#   --replace             Move files from "output/" to replace originals
#   --wet-run             Execute commands (default is dry-run)
#   -h, --help            Show this help message
#
# Default directory is the current working directory if not specified.

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
TARGET_DIR="."
COMPRESS=false
WET_RUN=false
REPLACE=false
SUB_FOLDER=true
EFFORT=5

# ── Resolve tinydng-cli ───────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${TINYDNG_CLI_CMD:-}" ]]; then
  TINYDNG="$TINYDNG_CLI_CMD"
elif [[ -x "$SCRIPT_DIR/tinydng-cli" ]]; then
  TINYDNG="$SCRIPT_DIR/tinydng-cli"
else
  TINYDNG="tinydng-cli"
fi

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --compress)       COMPRESS=true;    shift ;;
    --wet-run)        WET_RUN=true;     shift ;;
    --replace)        REPLACE=true;     shift ;;
    --sub-folder)     SUB_FOLDER=true;  shift ;;
    --no-sub-folder)  SUB_FOLDER=false; shift ;;
    --effort)
      if [[ -z "${2:-}" || ! "${2:-}" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}ERROR:${RESET} --effort requires a numeric value (1-10)" >&2; exit 1
      fi
      EFFORT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,/^[^#]/p' "$0" | sed 's/^# //;s/^#$//' | head -n -1
      exit 0 ;;
    -*)  echo "Unknown option: $1" >&2; exit 1 ;;
    *)   TARGET_DIR="$1"; shift ;;
  esac
done

# ── Validate effort ───────────────────────────────────────────────────────────
if [[ $EFFORT -lt 1 || $EFFORT -gt 10 ]]; then
  echo -e "${RED}ERROR:${RESET} --effort must be between 1 and 10 (got $EFFORT)" >&2; exit 1
fi

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v exiftool &>/dev/null; then
  echo -e "${RED}ERROR:${RESET} exiftool is not installed or not in PATH." >&2; exit 1
fi
if [[ ! -d "$TARGET_DIR" ]]; then
  echo -e "${RED}ERROR:${RESET} Directory not found: $TARGET_DIR" >&2; exit 1
fi
if $REPLACE && ! $COMPRESS; then
  echo -e "${RED}ERROR:${RESET} --replace requires --compress." >&2; exit 1
fi
if $WET_RUN && $COMPRESS && ! command -v "$TINYDNG" &>/dev/null; then
  echo -e "${RED}ERROR:${RESET} '$TINYDNG' not found." >&2
  echo    "  Download from https://tinydng.com/ or set TINYDNG_CLI_CMD=/path/to/binary" >&2
  exit 1
fi

TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
SCRIPT_START=$(date +%s)

# ── Helper: format elapsed seconds ───────────────────────────────────────────
elapsed() {
  local secs=$(( $(date +%s) - SCRIPT_START ))
  if [[ $secs -lt 60 ]]; then echo "${secs}s"; else echo "$(( secs / 60 ))m $(( secs % 60 ))s"; fi
}

# ── Banner ────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}=== Media Inventory Report ===${RESET}"
echo -e "  Directory : $TARGET_DIR"
if $COMPRESS; then
  echo -e "  Compress  : yes  (effort=$EFFORT, sub-folder=$SUB_FOLDER)"
  if $WET_RUN; then
    echo -e "  Wet-run   : ${GREEN}YES — commands will be executed${RESET}"
  else
    echo -e "  Wet-run   : ${YELLOW}NO — commands will be printed only${RESET}"
  fi
  if $REPLACE; then
    echo -e "  Replace   : ${GREEN}YES — outputs will replace originals after compression${RESET}"
  fi
fi
echo -e "  Scanning..."
echo

# ── Run exiftool once over everything ────────────────────────────────────────
TMPFILE="$(mktemp)"

# ── Signal handling ───────────────────────────────────────────────────────────
cleanup() {
  rm -f "$TMPFILE"
  echo -e "  ${DIM}Elapsed: $(elapsed)${RESET}\n"
}
cleanup_interrupted() {
  echo
  echo -e "${RED}[INTERRUPTED]${RESET} Script interrupted. Partial results may exist."
  cleanup
  exit 130
}
trap cleanup EXIT
trap cleanup_interrupted INT TERM

exiftool -r -q -csv -FileType -Compression -FileSize# \
  -ext dng  -ext DNG \
  -ext cr2  -ext CR2  -ext cr3  -ext CR3 \
  -ext nef  -ext NEF  -ext arw  -ext ARW \
  -ext orf  -ext ORF  -ext rw2  -ext RW2 \
  -ext raf  -ext RAF  -ext pef  -ext PEF \
  -ext srw  -ext SRW  -ext x3f  -ext X3F \
  -ext 3fr  -ext 3FR  -ext rwl  -ext RWL \
  -ext erf  -ext ERF  -ext kdc  -ext KDC \
  -ext mrw  -ext MRW  -ext nrw  -ext NRW \
  -ext srf  -ext SRF \
  -ext jpg  -ext JPG  -ext jpeg -ext JPEG \
  -ext mp4  -ext MP4  -ext mov  -ext MOV \
  -ext avi  -ext AVI  -ext mkv  -ext MKV \
  -ext mts  -ext MTS  -ext m2ts -ext M2TS \
  -ext m4v  -ext M4V  -ext wmv  -ext WMV \
  -ext mxf  -ext MXF \
  "$TARGET_DIR" > "$TMPFILE" 2>/dev/null || true

# ── Collect uncompressed DNG paths ───────────────────────────────────────────
UNCOMP_LIST=()
if $COMPRESS; then
  mapfile -t UNCOMP_LIST < <(
    awk -F',' '
    NR==1 { next }
    function trim(s) { gsub(/^[[:space:]"]+|[[:space:]"]+$/, "", s); return s }
    {
      path = trim($1); ft = toupper(trim($2)); c = tolower(trim($3))
      if (ft == "DNG" && (c == "1" || c == "uncompressed" || c == "none" || c == "" || c == "-"))
        print path
    }' "$TMPFILE"
  )
fi

# ── Inventory table ───────────────────────────────────────────────────────────
awk -v target="$TARGET_DIR" -F',' '
NR == 1 { next }
function trim(s) { gsub(/^[[:space:]"]+|[[:space:]"]+$/, "", s); return s }
function human(bytes,    units, i, val) {
  units[1]="B"; units[2]="KB"; units[3]="MB"; units[4]="GB"; units[5]="TB"
  val = bytes + 0
  for (i = 1; i <= 4; i++) { if (val < 1024) break; val = val / 1024 }
  if (i == 1) return sprintf("%d B", val)
  rounded = int(val * 10 + 0.5) / 10
  if (int(rounded) == rounded) return sprintf("%d %s", int(rounded), units[i])
  return sprintf("%.1f %s", rounded, units[i])
}
{
  path        = trim($1)
  filetype    = toupper(trim($2))
  compression = tolower(trim($3))
  filesize    = trim($4) + 0
  rel = path
  prefix = target "/"
  if (substr(rel, 1, length(prefix)) == prefix) rel = substr(rel, length(prefix) + 1)
  slash = index(rel, "/")
  group = (slash == 0) ? "(root)" : substr(rel, 1, slash - 1)
  size[group] += filesize; total_size += filesize
  if (filetype == "JPEG" || filetype == "JPG") {
    jpg[group]++
  } else if (filetype ~ /^(MP4|MOV|AVI|MKV|MTS|M2TS|M4V|WMV|MXF|R3D|BRAW|MPEG|MPG|3GP|FLV|WEBM)$/) {
    video[group]++
  } else if (filetype == "DNG") {
    c = compression
    if (c == "1" || c == "uncompressed" || c == "none" || c == "" || c == "-") dng_u[group]++
    else dng_c[group]++
  } else if (filetype ~ /^(CR2|CR3|NEF|ARW|ORF|RW2|RAF|PEF|SRW|X3F|3FR|RWL|ERF|KDC|MRW|NRW|SRF|RAW|IIQ|DCR|PTX|FFF|MEF|MOS|RWZ|CIFF)$/) {
    raw[group]++
  }
  groups[group] = 1
}
END {
  n = asorti(groups, sorted)
  for (i = 1; i <= n; i++) {
    if (sorted[i] == "(root)") { tmp = sorted[1]; sorted[1] = "(root)"; sorted[i] = tmp; break }
  }
  maxlen = 6
  for (i = 1; i <= n; i++) if (length(sorted[i]) > maxlen) maxlen = length(sorted[i])
  col = maxlen + 2
  fmt_hdr = sprintf("  %%-%ds  %%9s  %%9s  %%7s  %%6s  %%7s  %%7s  %%9s\n", col)
  fmt_row = sprintf("  %%-%ds  %%9d  %%9d  %%7d  %%6d  %%7d  %%7d  %%9s\n", col)
  divlen  = col + 2 + 9+2 + 9+2 + 7+2 + 6+2 + 7+2 + 7+2 + 9
  divider = "  "; for (i = 0; i < divlen; i++) divider = divider "─"
  printf fmt_hdr, "Folder", "DNG-Uncomp", "DNG-Comp", "RAW", "JPEG", "Video", "Total", "Size"
  print divider
  tu=0; tc=0; tr=0; tj=0; tv=0
  for (i = 1; i <= n; i++) {
    g = sorted[i]
    u  = (g in dng_u) ? dng_u[g] : 0; c  = (g in dng_c) ? dng_c[g] : 0
    ro = (g in raw)   ? raw[g]   : 0; jp = (g in jpg)   ? jpg[g]   : 0
    vi = (g in video) ? video[g] : 0; tot = u + c + ro + jp + vi
    printf fmt_row, g, u, c, ro, jp, vi, tot, human(size[g])
    tu+=u; tc+=c; tr+=ro; tj+=jp; tv+=vi
  }
  print divider
  printf fmt_row, "TOTAL", tu, tc, tr, tj, tv, tu+tc+tr+tj+tv, human(total_size)
  printf "\n"
}
' "$TMPFILE"

# ── Compress section ──────────────────────────────────────────────────────────
if ! $COMPRESS; then exit 0; fi

COUNT=${#UNCOMP_LIST[@]}
if [[ $COUNT -eq 0 ]]; then
  echo -e "${GREEN}✓ No uncompressed DNG files found — nothing to compress.${RESET}"
  echo; exit 0
fi

echo -e "${BOLD}=== Compress Uncompressed DNGs ===${RESET}"
echo -e "  Files   : $COUNT"
echo -e "  Options : --lossless --effort $EFFORT"
if $SUB_FOLDER; then
  echo -e "  Output  : output/ subfolder  (name: originalname_effort_${EFFORT}.dng)"
else
  echo -e "  Output  : in-place (temp-file swap)"
fi
if $WET_RUN; then
  echo -e "  Wet-run : ${GREEN}YES — executing all commands${RESET}"
else
  echo -e "  Wet-run : ${YELLOW}NO — printing all commands that would be run${RESET}"
fi
echo

# ── Helper: run or print a command ───────────────────────────────────────────
# Usage: run_or_print "description" cmd arg arg ...
# In dry-run mode: prints the command.
# In wet-run mode: executes it and returns its exit code.
run_or_print() {
  local desc="$1"; shift
  local cmd_str
  # Build a printable version with quoting
  cmd_str=$(printf ' %q' "$@")
  cmd_str="${cmd_str:1}"   # strip leading space

  if $WET_RUN; then
    "$@"
  else
    echo "  $cmd_str"
  fi
}

# ── Collect unique output dirs (for mkdir and cleanup) ───────────────────────
declare -A OUTPUT_DIRS_SEEN=()
for FILE in "${UNCOMP_LIST[@]}"; do
  if $SUB_FOLDER; then
    OUTPUT_DIRS_SEEN["$(dirname "$FILE")/output"]=1
  fi
done

COMP_OK=0
COMP_FAIL=0
COMP_FAIL_LIST=()
TOTAL_BEFORE=0
TOTAL_AFTER=0

# ── Step 1: mkdir for all output dirs ────────────────────────────────────────
if $SUB_FOLDER; then
  for OUT_DIR in "${!OUTPUT_DIRS_SEEN[@]}"; do
    run_or_print "mkdir" mkdir -p "$OUT_DIR"
  done
fi

# ── Step 2: compress each file ───────────────────────────────────────────────

for FILE in "${UNCOMP_LIST[@]}"; do
  SRC_DIR="$(dirname "$FILE")"
  BASENAME="$(basename "$FILE")"
  STEM="${BASENAME%.*}"

  if $SUB_FOLDER; then
    OUT_DIR="$SRC_DIR/output"
    OUT_FILE="$OUT_DIR/${STEM}_effort_${EFFORT}.dng"
  else
    OUT_DIR="$SRC_DIR"
    OUT_FILE="$SRC_DIR/.tinydng_tmp_${STEM}.dng"
  fi

  if $WET_RUN; then
    BEFORE=$(stat -f%z "$FILE" 2>/dev/null || stat -c%s "$FILE" 2>/dev/null || echo 0)
    printf "  ${CYAN}▶${RESET} %s → %s " "$FILE" "$OUT_FILE"
    if "$TINYDNG" --lossless --effort "$EFFORT" -i "$FILE" -o "$OUT_FILE" 2>/dev/null; then
      AFTER=$(stat -f%z "$OUT_FILE" 2>/dev/null || stat -c%s "$OUT_FILE" 2>/dev/null || echo 0)
      if [[ $AFTER -gt 0 ]]; then
        if ! $SUB_FOLDER; then
          mv "$OUT_FILE" "$FILE"
        fi
        SAVED=$(( BEFORE - AFTER ))
        PCT=$(( BEFORE > 0 ? SAVED * 100 / BEFORE : 0 ))
        echo -e "${GREEN}✓${RESET} $(numfmt --to=iec-i --suffix=B "$BEFORE" 2>/dev/null || echo "${BEFORE}B") → $(numfmt --to=iec-i --suffix=B "$AFTER" 2>/dev/null || echo "${AFTER}B") (~${PCT}%)"
        (( TOTAL_BEFORE += BEFORE )) || true
        (( TOTAL_AFTER  += AFTER  )) || true
        (( COMP_OK++ )) || true
      else
        rm -f "$OUT_FILE"
        echo -e "${RED}✗ empty output${RESET}"
        COMP_FAIL_LIST+=("$FILE :: output was empty")
        (( COMP_FAIL++ )) || true
      fi
    else
      EXIT_CODE=$?
      rm -f "$OUT_FILE"
      echo -e "${RED}✗ exit ${EXIT_CODE}${RESET}"
      COMP_FAIL_LIST+=("$FILE :: tinydng-cli exit ${EXIT_CODE}")
      (( COMP_FAIL++ )) || true
    fi
  else
    run_or_print "compress" "$TINYDNG" --lossless --effort "$EFFORT" -i "$FILE" -o "$OUT_FILE"
  fi
done

# ── Step 3 (dry-run only): print replace + cleanup commands ──────────────────
if ! $WET_RUN; then
  if $REPLACE; then
    for FILE in "${UNCOMP_LIST[@]}"; do
      SRC_DIR="$(dirname "$FILE")"
      STEM="$(basename "${FILE%.*}")"
      OUT_FILE="$SRC_DIR/output/${STEM}_effort_${EFFORT}.dng"
      run_or_print "replace" mv "$OUT_FILE" "$FILE"
    done
    for OUT_DIR in "${!OUTPUT_DIRS_SEEN[@]}"; do
      run_or_print "rmdir" rmdir "$OUT_DIR"
    done
  fi
  echo
  echo -e "${YELLOW}  Dry-run complete. Add --wet-run to execute.${RESET}"
  echo
  exit 0
fi

# ── Wet-run summary ───────────────────────────────────────────────────────────
REPLACE_OK=0
REPLACE_FAIL=0
REPLACE_FAIL_LIST=()

# ── Replace section (wet-run only) ───────────────────────────────────────────
if $REPLACE; then
  if [[ $COMP_FAIL -gt 0 ]]; then
    echo
    echo -e "${RED}${BOLD}WARNING:${RESET} $COMP_FAIL file(s) failed — skipping replace."
    echo; exit 1
  fi

  for FILE in "${UNCOMP_LIST[@]}"; do
    SRC_DIR="$(dirname "$FILE")"
    STEM="$(basename "${FILE%.*}")"
    OUT_FILE="$SRC_DIR/output/${STEM}_effort_${EFFORT}.dng"

    if [[ ! -f "$OUT_FILE" ]]; then
      echo -e "  ${RED}✗${RESET} Missing: $OUT_FILE"
      REPLACE_FAIL_LIST+=("$FILE :: output file missing")
      (( REPLACE_FAIL++ )) || true
      continue
    fi

    printf "  ${CYAN}▶${RESET} %s " "$OUT_FILE"
    if mv "$OUT_FILE" "$FILE"; then
      echo -e "${GREEN}✓${RESET}"
      (( REPLACE_OK++ )) || true
    else
      echo -e "${RED}✗ mv failed${RESET}"
      REPLACE_FAIL_LIST+=("$FILE :: mv failed")
      (( REPLACE_FAIL++ )) || true
    fi
  done

  if [[ $REPLACE_FAIL -eq 0 ]]; then
    for OUT_DIR in "${!OUTPUT_DIRS_SEEN[@]}"; do
      [[ -d "$OUT_DIR" ]] && rmdir "$OUT_DIR" 2>/dev/null || true
    done
  fi
fi

# ── Final summary ─────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}=== Summary ===${RESET}"
echo "  Compressed : $COMP_OK ok, $COMP_FAIL failed"
if $REPLACE; then
  echo "  Replaced   : $REPLACE_OK ok, $REPLACE_FAIL failed"
fi
if [[ $COMP_OK -gt 0 ]]; then
  TOTAL_SAVED=$(( TOTAL_BEFORE - TOTAL_AFTER ))
  TOTAL_PCT=$(( TOTAL_BEFORE > 0 ? TOTAL_SAVED * 100 / TOTAL_BEFORE : 0 ))
  echo "  Saved      : $(numfmt --to=iec-i --suffix=B "$TOTAL_SAVED" 2>/dev/null || echo "${TOTAL_SAVED}B")  ($(numfmt --to=iec-i --suffix=B "$TOTAL_BEFORE" 2>/dev/null || echo "${TOTAL_BEFORE}B") → $(numfmt --to=iec-i --suffix=B "$TOTAL_AFTER" 2>/dev/null || echo "${TOTAL_AFTER}B"), ~${TOTAL_PCT}%)"
fi
if [[ ${#COMP_FAIL_LIST[@]} -gt 0 || ${#REPLACE_FAIL_LIST[@]} -gt 0 ]]; then
  echo
  for F in "${COMP_FAIL_LIST[@]}" "${REPLACE_FAIL_LIST[@]}"; do
    echo -e "  ${RED}✗${RESET} $F"
  done
fi
echo

# Exit with error if there were any failures
if [[ $COMP_FAIL -gt 0 || ${#REPLACE_FAIL_LIST[@]} -gt 0 ]]; then
  exit 1
fi
