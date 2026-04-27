#!/usr/bin/env bash
#
# rip-compressor-kimi.sh
#
# Compress DVD/Bluray rips as-is: no cropping, no resizing, no re-encoding of
# subtitles, no discarding of chapters.  Every stream is mapped through and only
# re-encoded when the requirement explicitly allows it.
#
# ── Behaviour ────────────────────────────────────────────────────────────────
#   Video     -> AV1 (SVT-AV1)   CRF-based quality
#   Audio     -> Stereo (2 ch)  = FLAC (lossless)
#              -> Multi (>2 ch)  = Opus 256 kbit/s (lossy, high-quality)
#   Subtitles -> copied as-is
#   Chapters  -> copied as-is
#   Attachments / metadata / data -> copied as-is
#   HDR signalling -> preserved when detected
#
# ── Usage ──────────────────────────────────────────────────────────────────────
#   ./rip-compressor-kimi.sh [OPTIONS] <file_or_folder>
#
# ── Options ────────────────────────────────────────────────────────────────────
#   --try                  Encode only the first 5 minutes of each video.
#   --crf <0-63>           AV1 CRF value (default: 24). Lower = better quality.
#   --preset <0-13>        SVT-AV1 preset (default: 6). Lower = slower/better.
#   --out-dir <path>       Base directory for compressed outputs.
#                          Default: <input_dir>/compressed/  for folders,
#                                   <input>-compressed.mkv   for single files.
#   --bootstrap            Download a static ffmpeg build with SVT-AV1, FLAC
#                          and Opus support into
#                          ~/.local/share/rip-compressor-kimi/ffmpeg/.
#                          Run once; the script will use it automatically.
#   --wet-run              Actually execute the encode (default is dry-run).
#   --help                 Show this help message.
#
# ── Requirements ───────────────────────────────────────────────────────────────
#   - ffmpeg (libsvtav1, flac, libopus)
#     If your system ffmpeg is too old, run with --bootstrap to download a
#     static build with all required codecs.
#
# ── Notes ──────────────────────────────────────────────────────────────────────
#   - Output container is always MKV because it preserves every stream type,
#     including bitmap subtitles (PGS/VobSub) and chapter marks.
#   - Interlaced content is NOT deinterlaced; field order is left untouched.
#   - Files whose name already ends in "-compressed.mkv" are skipped to avoid
#     re-processing outputs.
#────────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
CRF=24
PRESET=6
TRY_MODE=false
WET_RUN=false
BOOTSTRAP=false
INPUT=""
OUT_DIR=""

FFMPEG_DIR="${HOME}/.local/share/rip-compressor-kimi/ffmpeg"
FFMPEG=""
FFPROBE=""

# ── Help ───────────────────────────────────────────────────────────────────────
usage() {
  sed -n '3,/^# ── Notes/p' "$0" | sed 's/^# //; s/^#//'
  exit 0
}

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --try)
      TRY_MODE=true
      shift
      ;;
    --crf)
      CRF="$2"
      shift 2
      ;;
    --preset)
      PRESET="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --bootstrap)
      BOOTSTRAP=true
      shift
      ;;
    --wet-run)
      WET_RUN=true
      shift
      ;;
    --help|-h)
      usage
      ;;
    -*)
      echo "ERROR: Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -n "$INPUT" ]]; then
        echo "ERROR: Only one input path allowed." >&2
        exit 1
      fi
      INPUT="$1"
      shift
      ;;
  esac
done

# ═══════════════════════════════════════════════════════════════════════════════
#  TOOLING
# ═══════════════════════════════════════════════════════════════════════════════

# ── Bootstrap: download static ffmpeg ──────────────────────────────────────────
bootstrap_ffmpeg() {
  echo "── Bootstrapping static ffmpeg (SVT-AV1 + FLAC + Opus) ─────────────"
  echo ""

  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64)  arch="linux64" ;;
    aarch64) arch="linuxarm64" ;;
    *)
      echo "ERROR: Unsupported architecture: $arch" >&2
      exit 1
      ;;
  esac

  local url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${arch}-gpl.tar.xz"
  local tmpdir
  tmpdir=$(mktemp -d)
  local tarball="${tmpdir}/ffmpeg.tar.xz"

  echo "  Source: $url"
  echo ""

  if ! command -v curl &>/dev/null; then
    echo "ERROR: curl is required for bootstrap." >&2
    rm -rf "$tmpdir"
    exit 1
  fi

  curl -L --progress-bar -o "$tarball" "$url"

  echo ""
  echo "  Extracting..."
  mkdir -p "$FFMPEG_DIR"
  tar -xf "$tarball" -C "$tmpdir" --strip-components=1

  mv -f "${tmpdir}/bin/ffmpeg"  "${FFMPEG_DIR}/ffmpeg"
  mv -f "${tmpdir}/bin/ffprobe" "${FFMPEG_DIR}/ffprobe"
  chmod +x "${FFMPEG_DIR}/ffmpeg" "${FFMPEG_DIR}/ffprobe"

  rm -rf "$tmpdir"

  echo ""
  echo "  Installed:"
  echo "    ${FFMPEG_DIR}/ffmpeg"
  echo "    ${FFMPEG_DIR}/ffprobe"
  echo ""
  echo "  Done."
}

# ── Resolve ffmpeg / ffprobe paths ────────────────────────────────────────────
resolve_ffmpeg() {
  if [[ -x "${FFMPEG_DIR}/ffmpeg" ]]; then
    FFMPEG="${FFMPEG_DIR}/ffmpeg"
    FFPROBE="${FFMPEG_DIR}/ffprobe"
    return
  fi

  if command -v ffmpeg &>/dev/null; then
    FFMPEG="$(command -v ffmpeg)"
    FFPROBE="$(command -v ffprobe 2>/dev/null || echo "")"
    return
  fi

  echo "ERROR: ffmpeg not found. Run with --bootstrap to download it." >&2
  exit 1
}

# ── Check required encoders ──────────────────────────────────────────────────
check_encoders() {
  local missing=()
  local enc
  enc=$("$FFMPEG" -encoders 2>/dev/null || true)

  if ! grep -q 'libsvtav1' <<< "$enc"; then
    missing+=("libsvtav1  (AV1 video encoder)")
  fi
  if ! grep -q '^ .A.... flac' <<< "$enc"; then
    missing+=("flac       (lossless audio encoder)")
  fi
  if ! grep -q 'libopus' <<< "$enc"; then
    missing+=("libopus    (Opus audio encoder)")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: ffmpeg is missing required encoders:" >&2
    for m in "${missing[@]}"; do
      echo "  - $m" >&2
    done
    echo "" >&2
    echo "Run with --bootstrap to download a compatible static build:" >&2
    echo "  $0 --bootstrap" >&2
    exit 1
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
#  PER-FILE LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

# ── Detect HDR transfer characteristic ────────────────────────────────────────
detect_hdr() {
  local file="$1"
  local trc
  trc=$("$FFPROBE" -v error -select_streams v:0 \
    -show_entries stream=color_transfer -of csv=p=0 "$file" 2>/dev/null || true)

  case "$trc" in
    smpte2084|pq|16) echo "hdr_pq" ;;
    arib-std-b67|hlg|18) echo "hdr_hlg" ;;
    *) echo "sdr" ;;
  esac
}

# ── Build ffmpeg command for one file ─────────────────────────────────────────
build_cmd() {
  local input="$1"
  local output="$2"

  local hdr_type
  hdr_type=$(detect_hdr "$input")

  # ---- Base command ----------------------------------------------------------
  local cmd=("$FFMPEG")

  # Try-mode limit (5 minutes)
  if [[ "$TRY_MODE" == "true" ]]; then
    cmd+=(-t 300)
  fi

  cmd+=(-i "$input" -y)

  # Map every stream and preserve chapters / metadata
  cmd+=(-map 0 -map_chapters 0 -map_metadata 0)

  # ---- Video (all video streams) ---------------------------------------------
  cmd+=(-c:v libsvtav1 -crf "$CRF" -preset "$PRESET" \
        -svtav1-params "tune=0:film-grain=8")

  if [[ "$hdr_type" == "hdr_pq" ]]; then
    cmd+=(-color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc)
  elif [[ "$hdr_type" == "hdr_hlg" ]]; then
    cmd+=(-color_primaries bt2020 -color_trc arib-std-b67 -colorspace bt2020nc)
  fi

  # ---- Audio (per-stream based on channel count) ------------------------------
  local audio_csv
  audio_csv=$("$FFPROBE" -v error -select_streams a \
    -show_entries stream=channels -of csv=p=0 "$input" 2>/dev/null || true)

  local aidx=0
  while IFS= read -r ch; do
    [[ -z "$ch" ]] && continue
    if [[ "$ch" == "2" ]]; then
      cmd+=(-c:a:"$aidx" flac)
    else
      # Multi-channel: Opus at 256 kbit/s (excellent quality for surround)
      cmd+=(-c:a:"$aidx" libopus -b:a:"$aidx" 256k)
    fi
    ((aidx++))
  done <<< "$audio_csv"

  # ---- Subtitles / data / attachments -----------------------------------------
  cmd+=(-c:s copy -c:d copy -c:t copy)

  # ---- Output -----------------------------------------------------------------
  cmd+=("$output")

  printf '%s\n' "${cmd[*]}"
}

# ── Process a single video file ────────────────────────────────────────────────
process_file() {
  local infile="$1"
  local outfile="$2"

  echo ""
  echo "  File:   $infile"
  echo "  Output: $outfile"

  # Create output directory if needed
  local outdir
  outdir=$(dirname "$outfile")
  mkdir -p "$outdir"

  local cmd
  cmd=$(build_cmd "$infile" "$outfile")

  if [[ "$WET_RUN" != "true" ]]; then
    echo "  (dry-run — use --wet-run to execute)"
    echo "  $cmd"
    return
  fi

  echo "  Encoding..."
  eval "$cmd"

  # Stream sanity check
  if [[ -n "$FFPROBE" ]] && [[ -x "$FFPROBE" ]]; then
    local in_streams out_streams
    in_streams=$("$FFPROBE" -v error -show_entries format=nb_streams \
      -of csv=p=0 "$infile" 2>/dev/null || echo "?")
    out_streams=$("$FFPROBE" -v error -show_entries format=nb_streams \
      -of csv=p=0 "$outfile" 2>/dev/null || echo "?")
    echo "  Streams: $in_streams -> $out_streams"
  fi

  echo "  Done."
}

# ── Find video files recursively ───────────────────────────────────────────────
find_videos() {
  local dir="$1"
  find "$dir" -type f \( \
    -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.m4v' -o \
    -iname '*.avi' -o -iname '*.mov' -o -iname '*.ts' -o \
    -iname '*.m2ts' -o -iname '*.mts' -o -iname '*.vob' -o \
    -iname '*.mpg' -o -iname '*.mpeg' -o -iname '*.wmv' \
  \) ! -iname '*-compressed.mkv' -print
}

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

# --bootstrap requires no input
if [[ "$BOOTSTRAP" == "true" ]]; then
  bootstrap_ffmpeg
  exit 0
fi

# Validate input
if [[ -z "$INPUT" ]]; then
  echo "ERROR: No input file or folder specified." >&2
  echo "Usage: $0 [OPTIONS] <file_or_folder>" >&2
  exit 1
fi

if [[ ! -e "$INPUT" ]]; then
  echo "ERROR: Input path not found: $INPUT" >&2
  exit 1
fi

# Resolve ffmpeg
resolve_ffmpeg
check_encoders

# ── Single file mode ───────────────────────────────────────────────────────────
if [[ -f "$INPUT" ]]; then
  # Determine output path
  if [[ -n "$OUT_DIR" ]]; then
    BASENAME=$(basename "${INPUT%.*}")
    OUTPUT="${OUT_DIR}/${BASENAME}-compressed.mkv"
    mkdir -p "$OUT_DIR"
  else
    BASENAME="${INPUT%.*}"
    OUTPUT="${BASENAME}-compressed.mkv"
  fi

  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║      rip-compressor-kimi.sh — AV1 Rip Compressor            ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Mode:    $([[ "$TRY_MODE" == "true" ]] && echo "TRY (5 min)" || echo "FULL")"
  echo "  Video:   AV1 (SVT-AV1)  CRF=$CRF  Preset=$PRESET"
  echo "  Audio:   Stereo -> FLAC | Multi -> Opus 256k"
  echo "  ffmpeg:  $FFMPEG"

  hdr_type=$(detect_hdr "$INPUT")
  [[ "$hdr_type" != "sdr" ]] && echo "  HDR:     $hdr_type (preserved)"

  process_file "$INPUT" "$OUTPUT"

  echo ""
  echo "── All done ──────────────────────────────────────────────────"
  exit 0
fi

# ── Folder mode ────────────────────────────────────────────────────────────────
if [[ -d "$INPUT" ]]; then
  # Normalise to absolute path
  INPUT=$(cd "$INPUT" && pwd)

  # Output base directory
  if [[ -n "$OUT_DIR" ]]; then
    OUT_BASE="$OUT_DIR"
  else
    OUT_BASE="${INPUT}/compressed"
  fi
  mkdir -p "$OUT_BASE"

  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║      rip-compressor-kimi.sh — Batch AV1 Rip Compressor      ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Input:   $INPUT"
  echo "  Output:  $OUT_BASE"
  echo "  Mode:    $([[ "$TRY_MODE" == "true" ]] && echo "TRY (5 min)" || echo "FULL")"
  echo "  Video:   AV1 (SVT-AV1)  CRF=$CRF  Preset=$PRESET"
  echo "  Audio:   Stereo -> FLAC | Multi -> Opus 256k"
  echo "  ffmpeg:  $FFMPEG"
  echo ""

  local count=0
  while IFS= read -r -d '' file; do
    count=$((count + 1))
  done < <(find_videos "$INPUT" -print0)

  if [[ "$count" -eq 0 ]]; then
    echo "  No video files found."
    exit 0
  fi

  echo "  Found $count video file(s)."
  echo ""

  local current=0
  while IFS= read -r -d '' file; do
    current=$((current + 1))

    # Compute mirrored output path
    local rel
    rel="${file#${INPUT}/}"
    local outname
    outname="${rel%.*}-compressed.mkv"
    local outfile="${OUT_BASE}/${outname}"

    # Skip if already exists
    if [[ -f "$outfile" ]]; then
      echo "[$current/$count] SKIP (already exists): $rel"
      continue
    fi

    echo "[$current/$count] ──────────────────────────────────────────────"
    process_file "$file" "$outfile"
  done < <(find_videos "$INPUT" -print0)

  echo ""
  echo "── Batch complete ────────────────────────────────────────────"
  exit 0
fi

echo "ERROR: Input is neither a file nor a directory: $INPUT" >&2
exit 1
