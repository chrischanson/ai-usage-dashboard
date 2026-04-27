#!/usr/bin/env bash
#
# rip-compressor-glm.sh
#
# Lossless-as-possible compression of DVD / Blu-ray rips.
#   Video  :  AV1 (SVT-AV1) — the best general-purpose codec available
#   Audio  :  Stereo  → FLAC (lossless)
#              Surround → Opus 256 kbps (transparent for 5.1/7.1)
#   Subs   :  Bitstream copy (bitmap + text, no re-encode)
#   Chapters: Preserved verbatim
#   HDR    :  Colour signalling forwarded when detected
#
# ─────────────────────────────────────────────────────────────────────────────
#   ./rip-compressor-glm.sh [OPTIONS] <file_or_directory>
# ─────────────────────────────────────────────────────────────────────────────
#
# OPTIONS
#   --try              Encode only the first 5 minutes (quality preview).
#   --crf  <0-63>      AV1 CRF (default 24).  Lower → better / bigger.
#   --preset <0-13>    SVT-AV1 preset (default 6).  Lower → slower / better.
#   --out-dir <path>   Where compressed files are written.
#                        Single-file default  : <name>-compressed.mkv
#                        Directory default    : <input>/compressed/
#   --bootstrap        Download a static ffmpeg with all required codecs
#                        into ~/.local/share/rip-compressor-glm/ffmpeg/.
#                        Run once; the script auto-detects it afterwards.
#   --wet-run          Actually execute (default is dry-run: print only).
#   --help | -h        This message.
#
# REQUIREMENTS
#   ffmpeg  (libsvtav1 + flac + libopus).  Run --bootstrap if yours is too old.
#
# NOTES
#   • Output is always MKV — the only container that reliably holds every
#     stream type (bitmap subs, chapters, multi-audio, HDR).
#   • Files named *-compressed.mkv are automatically skipped when scanning
#     directories, so re-running is safe.
#   • No video filters are applied — no cropping, scaling, deinterlacing,
#     or colour-space conversion.  The picture is untouched except for
#     the codec change itself.
#───────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
CRF=24
PRESET=6
TRY_MODE=false
WET_RUN=false
BOOTSTRAP=false
INPUT=""
OUT_DIR=""

FFMPEG_DIR="${HOME}/.local/share/rip-compressor-glm/ffmpeg"
FFMPEG=""
FFPROBE=""

# Video extensions to look for when scanning directories
VIDEO_EXTS=(mkv mp4 m4v avi mov m2ts ts mts vob mpg mpeg wmv flv webm)

# ── Usage ──────────────────────────────────────────────────────────────────────
usage() {
  sed -n '3,/^# ───/p' "$0" | sed 's/^# \?//'
  exit 0
}

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --try)       TRY_MODE=true;  shift ;;
    --crf)       CRF="$2";       shift 2 ;;
    --preset)    PRESET="$2";    shift 2 ;;
    --out-dir)   OUT_DIR="$2";   shift 2 ;;
    --bootstrap) BOOTSTRAP=true; shift ;;
    --wet-run)   WET_RUN=true;  shift ;;
    --help|-h)   usage ;;
    -*)          echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -n "$INPUT" ]]; then
        echo "ERROR: Only one input path allowed." >&2; exit 1
      fi
      INPUT="$1"; shift
      ;;
  esac
done

# ═════════════════════════════════════════════════════════════════════════════
#  TOOLCHAIN
# ═════════════════════════════════════════════════════════════════════════════

bootstrap_ffmpeg() {
  echo "── Bootstrapping ffmpeg (SVT-AV1 + FLAC + Opus) ────────────────────"
  echo ""

  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64)  arch="linux64"  ;;
    aarch64) arch="linuxarm64" ;;
    *)       echo "ERROR: Unsupported arch: $arch" >&2; exit 1 ;;
  esac

  local url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${arch}-gpl.tar.xz"
  local tmpdir
  tmpdir=$(mktemp -d)

  echo "  Source : $url"
  echo ""

  command -v curl &>/dev/null || { echo "ERROR: curl required." >&2; rm -rf "$tmpdir"; exit 1; }

  curl -L --progress-bar -o "${tmpdir}/ffmpeg.tar.xz" "$url"

  echo ""
  echo "  Extracting..."
  mkdir -p "$FFMPEG_DIR"
  tar -xf "${tmpdir}/ffmpeg.tar.xz" -C "$tmpdir" --strip-components=1

  mv -f "${tmpdir}/bin/ffmpeg"  "${FFMPEG_DIR}/ffmpeg"
  mv -f "${tmpdir}/bin/ffprobe" "${FFMPEG_DIR}/ffprobe"
  chmod +x "${FFMPEG_DIR}/ffmpeg" "${FFMPEG_DIR}/ffprobe"

  rm -rf "$tmpdir"

  echo ""
  echo "  Installed → ${FFMPEG_DIR}/ffmpeg"
  echo "  Done.  Re-run the script without --bootstrap to start encoding."
}

resolve_ffmpeg() {
  # 1) Prefer bootstrapped build
  if [[ -x "${FFMPEG_DIR}/ffmpeg" ]]; then
    FFMPEG="${FFMPEG_DIR}/ffmpeg"
    FFPROBE="${FFMPEG_DIR}/ffprobe"
    return
  fi
  # 2) Fall back to system
  if command -v ffmpeg &>/dev/null; then
    FFMPEG="$(command -v ffmpeg)"
    FFPROBE="$(command -v ffprobe 2>/dev/null || true)"
    return
  fi
  echo "ERROR: ffmpeg not found.  Run with --bootstrap to download it." >&2
  exit 1
}

check_encoders() {
  local enc missing=()
  enc=$("$FFMPEG" -encoders 2>/dev/null || true)

  grep -q 'libsvtav1' <<< "$enc" || missing+=("libsvtav1  (AV1 video)")
  grep -q 'flac'       <<< "$enc" || missing+=("flac       (lossless audio)")
  grep -q 'libopus'    <<< "$enc" || missing+=("libopus    (Opus audio)")

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing encoders:" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "Run with --bootstrap to get a compatible ffmpeg." >&2
    exit 1
  fi
}

# ═════════════════════════════════════════════════════════════════════════════
#  PER-FILE HELPERS
# ═════════════════════════════════════════════════════════════════════════════

detect_hdr() {
  local trc
  trc=$("$FFPROBE" -v error -select_streams v:0 \
    -show_entries stream=color_transfer -of csv=p=0 "$1" 2>/dev/null || true)
  case "$trc" in
    smpte2084|pq|16)   echo "pq"  ;;
    arib-std-b67|hlg|18) echo "hlg" ;;
    *)                  echo "sdr" ;;
  esac
}

# Returns the number of audio streams in the file
count_audio_streams() {
  "$FFPROBE" -v error -select_streams a \
    -show_entries stream=index -of csv=p=0 "$1" 2>/dev/null | wc -l
}

# Build the full ffmpeg command for one input → one output
build_cmd() {
  local input="$1" output="$2"
  local hdr
  hdr=$(detect_hdr "$input")

  # ── Global flags ────────────────────────────────────────────────────────────
  local cmd=("$FFMPEG" -y)

  # Try mode: 5-minute cap
  [[ "$TRY_MODE" == "true" ]] && cmd+=(-t 300)

  cmd+=(-i "$input")

  # Map everything + chapters + metadata
  cmd+=(-map 0 -map_chapters 0 -map_metadata 0)

  # ── Video ───────────────────────────────────────────────────────────────────
  cmd+=(-c:v libsvtav1 -crf "$CRF" -preset "$PRESET")
  cmd+=(-svtav1-params "tune=0:film-grain=8")

  case "$hdr" in
    pq)  cmd+=(-color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc) ;;
    hlg) cmd+=(-color_primaries bt2020 -color_trc arib-std-b67 -colorspace bt2020nc) ;;
  esac

  # ── Audio (per-stream channel-based decision) ──────────────────────────────
  local ch_csv
  ch_csv=$("$FFPROBE" -v error -select_streams a \
    -show_entries stream=channels -of csv=p=0 "$input" 2>/dev/null || true)

  local idx=0
  while IFS= read -r ch; do
    [[ -z "$ch" ]] && continue
    if [[ "$ch" -le 2 ]]; then
      # Stereo / mono → lossless FLAC
      cmd+=(-c:a:"$idx" flac)
    else
      # Surround (5.1 / 7.1) → Opus 256 kbps
      cmd+=(-c:a:"$idx" libopus -b:a:"$idx" 256k)
    fi
    ((idx++))
  done <<< "$ch_csv"

  # ── Subtitles / data / attachments ──────────────────────────────────────────
  cmd+=(-c:s copy -c:d copy -c:t copy)

  # ── Output ──────────────────────────────────────────────────────────────────
  cmd+=("$output")

  printf '%s\n' "${cmd[*]}"
}

# ═════════════════════════════════════════════════════════════════════════════
#  PROCESSING
# ═════════════════════════════════════════════════════════════════════════════

process_one() {
  local input="$1" output="$2"

  echo ""
  echo "  ┌─ Source  : $input"
  echo "  │ Output  : $output"

  # Ensure output directory exists
  mkdir -p "$(dirname "$output")"

  # Avoid overwriting the input
  if [[ "$(readlink -f "$input" 2>/dev/null || echo "$input")" \
     == "$(readlink -f "$output" 2>/dev/null || echo "$output")" ]]; then
    echo "  └─ SKIP   : output would overwrite input"
    return
  fi

  local cmd
  cmd=$(build_cmd "$input" "$output")

  if [[ "$WET_RUN" != "true" ]]; then
    echo "  │ Mode    : dry-run (use --wet-run to execute)"
    echo "  │ Command :"
    echo "  │   $cmd"
    echo "  └─────────────────────────────────────────────────"
    return
  fi

  echo "  │ Mode    : wet-run"
  echo "  │ Encoding..."
  eval "$cmd"

  # Quick stream-count sanity check
  if [[ -x "$FFPROBE" ]]; then
    local n_in n_out
    n_in=$("$FFPROBE" -v error -show_entries format=nb_streams \
           -of csv=p=0 "$input" 2>/dev/null || echo "?")
    n_out=$("$FFPROBE" -v error -show_entries format=nb_streams \
            -of csv=p=0 "$output" 2>/dev/null || echo "?")
    echo "  │ Streams : $n_in → $n_out"
  fi

  echo "  └─ Done"
}

# Build a find-compatible extension filter
build_ext_filter() {
  local first=true
  printf '('
  for ext in "${VIDEO_EXTS[@]}"; do
    $first || printf ' -o'
    printf ' -iname *.%s' "$ext"
    first=false
  done
  printf ' )'
}

# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

# --bootstrap is standalone
if [[ "$BOOTSTRAP" == "true" ]]; then
  bootstrap_ffmpeg
  exit 0
fi

if [[ -z "$INPUT" ]]; then
  echo "ERROR: No input specified." >&2
  echo "Usage: $0 [OPTIONS] <file_or_directory>" >&2
  exit 1
fi

if [[ ! -e "$INPUT" ]]; then
  echo "ERROR: Not found: $INPUT" >&2
  exit 1
fi

resolve_ffmpeg
check_encoders

# ── Single file ────────────────────────────────────────────────────────────────
if [[ -f "$INPUT" ]]; then
  if [[ -n "$OUT_DIR" ]]; then
    OUTPUT="${OUT_DIR}/$(basename "${INPUT%.*}")-compressed.mkv"
    mkdir -p "$OUT_DIR"
  else
    OUTPUT="${INPUT%.*}-compressed.mkv"
  fi

  echo "╔════════════════════════════════════════════════════════════╗"
  echo "║        rip-compressor-glm.sh  ·  AV1 Rip Compressor       ║"
  echo "╚════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Video  : AV1 (SVT-AV1)  CRF $CRF  Preset $PRESET"
  echo "  Audio  : ≤2ch → FLAC  |  >2ch → Opus 256k"
  echo "  ffmpeg : $FFMPEG"
  [[ "$TRY_MODE" == "true" ]] && echo "  Try    : 5-minute preview"
  local hdr
  hdr=$(detect_hdr "$INPUT")
  [[ "$hdr" != "sdr" ]] && echo "  HDR    : $hdr (preserved)"

  process_one "$INPUT" "$OUTPUT"

  echo ""
  echo "── Finished ─────────────────────────────────────────────────"
  exit 0
fi

# ── Directory (recursive batch) ────────────────────────────────────────────────
if [[ -d "$INPUT" ]]; then
  INPUT="$(cd "$INPUT" && pwd)"   # absolute

  if [[ -n "$OUT_DIR" ]]; then
    OUT_BASE="$OUT_DIR"
  else
    OUT_BASE="${INPUT}/compressed"
  fi
  mkdir -p "$OUT_BASE"

  echo "╔════════════════════════════════════════════════════════════╗"
  echo "║     rip-compressor-glm.sh  ·  Batch AV1 Rip Compressor    ║"
  echo "╚════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Source   : $INPUT"
  echo "  Output   : $OUT_BASE"
  echo "  Video    : AV1 (SVT-AV1)  CRF $CRF  Preset $PRESET"
  echo "  Audio    : ≤2ch → FLAC  |  >2ch → Opus 256k"
  echo "  ffmpeg   : $FFMPEG"
  [[ "$TRY_MODE" == "true" ]] && echo "  Try      : 5-minute preview"
  echo ""

  # Collect files
  local ext_filter
  ext_filter=$(build_ext_filter)

  local files=()
  while IFS= read -r -d '' f; do
    files+=("$f")
  done < <(eval find "'$INPUT'" -type f "$ext_filter" '! -iname \"*-compressed.mkv\"' -print0 2>/dev/null)

  local total=${#files[@]}
  if [[ "$total" -eq 0 ]]; then
    echo "  No video files found."
    exit 0
  fi

  echo "  Found $total video file(s)."
  echo ""

  for i in "${!files[@]}"; do
    local f="${files[$i]}"
    local n=$((i + 1))

    # Mirror directory structure under OUT_BASE
    local rel="${f#"${INPUT}"/}"
    local outname="${rel%.*}-compressed.mkv"
    local outfile="${OUT_BASE}/${outname}"

    # Skip existing outputs
    if [[ -f "$outfile" ]]; then
      echo "[$n/$total] SKIP (exists): $rel"
      continue
    fi

    echo "[$n/$total] ──────────────────────────────────────────────────"
    process_one "$f" "$outfile"
  done

  echo ""
  echo "── Batch complete ($total files) ──────────────────────────────"
  exit 0
fi

echo "ERROR: Not a file or directory: $INPUT" >&2
exit 1
