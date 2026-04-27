#!/usr/bin/env bash
#
# compress-rip.sh
#
# Compress DVD/Bluray rips as-is: no cropping, no resizing, no other changes.
#   - Video:  AV1 (SVT-AV1) via ffmpeg, CRF-based quality
#   - Audio:  Lossless (FLAC) — all tracks preserved
#   - Subtitles: All streams copied (bitmap subtitles as-is, text subtitles as-is)
#
# Try mode (--try): encodes only the first 5 minutes so you can evaluate
# quality/speed before committing to a full encode.
#
# ── Usage ─────────────────────────────────────────────────────────────────────
#   ./compress-rip.sh [OPTIONS] <input.mkv>
#
# ── Options ───────────────────────────────────────────────────────────────────
#   --try                  Encode only the first 5 minutes of the video.
#   --crf <0-63>           AV1 CRF value (default: 24). Lower = better quality.
#   --preset <0-13>        SVT-AV1 preset (default: 6). Lower = slower/better.
#   --output <path>        Output file path (default: <input>-compressed.mkv).
#   --bootstrap            Download a static ffmpeg build with SVT-AV1 & FLAC
#                          support into ~/.local/share/compress-rip/ffmpeg/.
#                          Run once, then the script will use it automatically.
#   --wet-run              Actually execute the encode (default is dry-run).
#   --help                 Show this help message.
#
# ── Requirements ──────────────────────────────────────────────────────────────
#   - ffmpeg (built with libsvtav1, libflac support)
#     If your system ffmpeg is too old, run with --bootstrap to download a
#     static build with all required codecs.
#   - mkvmerge (optional, for verifying streams)
#
# ── Notes ─────────────────────────────────────────────────────────────────────
#   - Bitmap subtitles (PGS, VobSub) are copied as-is; they cannot be
#     re-encoded losslessly and must be kept in a compatible container (MKV).
#   - FLAC is used for lossless audio compression regardless of the source codec.
#     Multi-channel layouts are preserved.
#   - The script always outputs MKV since it supports all required stream types.
#   - HDR metadata is preserved via --color-trace options when detected.
#   - For DVD rips with interlaced content, consider adding a separate
#     deinterlace pass; this script does NOT alter the video in any way.
#───────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
CRF=24
PRESET=6
TRY_MODE=false
DRY_RUN=true
BOOTSTRAP=false
OUTPUT=""
INPUT=""

# ── Paths ────────────────────────────────────────────────────────────────────
FFMPEG_DIR="${HOME}/.local/share/compress-rip/ffmpeg"
FFMPEG=""
FFPROBE=""

# ── Help ─────────────────────────────────────────────────────────────────────
usage() {
  sed -n '3,/^$/p' "$0"
  exit 0
}

# ── Argument parsing ─────────────────────────────────────────────────────────
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
    --output)
      OUTPUT="$2"
      shift 2
      ;;
    --bootstrap)
      BOOTSTRAP=true
      shift
      ;;
    --wet-run)
      DRY_RUN=false
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
        echo "ERROR: Multiple input files specified. Only one input is supported." >&2
        exit 1
      fi
      INPUT="$1"
      shift
      ;;
  esac
done

# ── Bootstrap: download static ffmpeg ──────────────────────────────────────
bootstrap_ffmpeg() {
  echo "── Downloading static ffmpeg with SVT-AV1 & FLAC ──────────────────"
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

  # BtbN provides GPL builds with libsvtav1
  local url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${arch}-gpl.tar.xz"
  local tmpdir
  tmpdir=$(mktemp -d)
  local tarball="${tmpdir}/ffmpeg.tar.xz"

  echo "  Downloading from:"
  echo "  $url"
  echo ""

  if ! command -v curl &>/dev/null; then
    echo "ERROR: curl is required for bootstrap. Install curl and try again." >&2
    rm -rf "$tmpdir"
    exit 1
  fi

  curl -L --progress-bar -o "$tarball" "$url"

  echo ""
  echo "  Extracting..."
  mkdir -p "$FFMPEG_DIR"
  tar -xf "$tarball" -C "$tmpdir" --strip-components=1

  # Move binaries into place
  mv -f "${tmpdir}/bin/ffmpeg"  "${FFMPEG_DIR}/ffmpeg"
  mv -f "${tmpdir}/bin/ffprobe" "${FFMPEG_DIR}/ffprobe"
  chmod +x "${FFMPEG_DIR}/ffmpeg" "${FFMPEG_DIR}/ffprobe"

  rm -rf "$tmpdir"

  echo ""
  echo "  Installed to:"
  echo "    ${FFMPEG_DIR}/ffmpeg"
  echo "    ${FFMPEG_DIR}/ffprobe"
  echo ""
  echo "  Done! The script will now use this ffmpeg automatically."
}

# ── Resolve ffmpeg/ffprobe paths ───────────────────────────────────────────
resolve_ffmpeg() {
  # Prefer the bootstrapped version if it exists
  if [[ -x "${FFMPEG_DIR}/ffmpeg" ]]; then
    FFMPEG="${FFMPEG_DIR}/ffmpeg"
    FFPROBE="${FFMPEG_DIR}/ffprobe"
    return
  fi

  # Fall back to system ffmpeg
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

  if ! "$FFMPEG" -encoders 2>/dev/null | grep -q 'libsvtav1'; then
    missing+=("libsvtav1 (AV1 video encoder)")
  fi

  if ! "$FFMPEG" -encoders 2>/dev/null | grep -q 'flac'; then
    missing+=("flac (lossless audio encoder)")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Your ffmpeg is missing required encoders:" >&2
    for m in "${missing[@]}"; do
      echo "  - $m" >&2
    done
    echo "" >&2
    echo "Run with --bootstrap to download a static ffmpeg with all codecs:" >&2
    echo "  $0 --bootstrap" >&2
    exit 1
  fi
}

# Handle --bootstrap early (doesn't need an input file)
if [[ "$BOOTSTRAP" == "true" ]]; then
  bootstrap_ffmpeg
  exit 0
fi

# ── Validate ────────────────────────────────────────────────────────────────
if [[ -z "$INPUT" ]]; then
  echo "ERROR: No input file specified." >&2
  echo "Usage: $0 [OPTIONS] <input.mkv>" >&2
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: Input file not found: $INPUT" >&2
  exit 1
fi

# Determine output path
if [[ -z "$OUTPUT" ]]; then
  BASENAME="${INPUT%.*}"
  OUTPUT="${BASENAME}-compressed.mkv"
fi

# Avoid overwriting the source file
if [[ "$(readlink -f "$INPUT" 2>/dev/null || echo "$INPUT")" == "$(readlink -f "$OUTPUT" 2>/dev/null || echo "$OUTPUT")" ]]; then
  echo "ERROR: Output file would overwrite input. Specify a different --output path." >&2
  exit 1
fi

# ── Resolve and validate ffmpeg ──────────────────────────────────────────────
resolve_ffmpeg
check_encoders

# ── Detect HDR ──────────────────────────────────────────────────────────────
detect_hdr() {
  local file="$1"
  # Check for HDR transfer characteristics (PQ = 16, HLG = 18)
  local color_trc
  color_trc=$("$FFPROBE" -v error -select_streams v:0 \
    -show_entries stream=color_transfer \
    -of csv=p=0 "$file" 2>/dev/null || echo "")

  case "$color_trc" in
    smpte2084|pq|16)
      echo "hdr_pq"
      ;;
    arib-std-b67|hlg|18)
      echo "hdr_hlg"
      ;;
    *)
      echo "sdr"
      ;;
  esac
}

# ── Build ffmpeg command ────────────────────────────────────────────────────
build_cmd() {
  local input="$1"
  local output="$2"
  local crf="$3"
  local preset="$4"
  local try_mode="$5"

  local hdr_type
  hdr_type=$(detect_hdr "$input")

  # Base video encoding arguments
  local video_args=(
    -c:v libsvtav1
    -crf "$crf"
    -preset "$preset"
    -svtav1-params "tune=0:film-grain=8"
  )

  # Preserve HDR signalling when detected
  if [[ "$hdr_type" == "hdr_pq" ]]; then
    video_args+=(
      -color_primaries bt2020
      -color_trc smpte2084
      -colorspace bt2020nc
    )
  elif [[ "$hdr_type" == "hdr_hlg" ]]; then
    video_args+=(
      -color_primaries bt2020
      -color_trc arib-std-b67
      -colorspace bt2020nc
    )
  fi

  # Try mode: limit to first 5 minutes
  local input_args=()
  if [[ "$try_mode" == "true" ]]; then
    input_args=(-t 300)
  fi

  # Assemble the full command:
  #   - Map ALL streams (video, audio, subtitle, attachment, data)
  #   - Video:  AV1 encode with SVT-AV1
  #   - Audio:  FLAC (lossless) for all audio streams
  #   - Subtitles: copy all subtitle streams as-is
  #   - Attachments: copy (fonts etc.)
  #   - Data: copy (e.g. HDR dynamic metadata)
  local cmd=(
    "$FFMPEG"
    -i "$input"
    "${input_args[@]}"
    -map 0
    -c:v:0 "${video_args[@]}"
    -c:a flac
    -c:s copy
    -c:d copy
    -c:t copy
    -map_metadata 0
    -movflags +faststart
    "$output"
  )

  printf '%s\n' "${cmd[*]}"
}

# ── Main ────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║            compress-rip.sh — AV1 Rip Compressor         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Input:   $INPUT"
echo "  Output:  $OUTPUT"
echo "  Video:   AV1 (SVT-AV1)  CRF=$CRF  Preset=$PRESET"
echo "  ffmpeg:  $FFMPEG"

if [[ "$TRY_MODE" == "true" ]]; then
  echo "  Mode:    TRY — encoding first 5 minutes only"
else
  echo "  Mode:    FULL encode"
fi

hdr_type=$(detect_hdr "$INPUT")
if [[ "$hdr_type" != "sdr" ]]; then
  echo "  HDR:     Detected $hdr_type — preserving HDR metadata"
else
  echo "  HDR:     SDR"
fi

echo "  Audio:   FLAC (lossless)"
echo "  Subs:    All copied as-is"
echo ""

# Build the command
CMD=$(build_cmd "$INPUT" "$OUTPUT" "$CRF" "$PRESET" "$TRY_MODE")

if [[ "$DRY_RUN" == "true" ]]; then
  echo "── Dry Run ──────────────────────────────────────────────"
  echo ""
  echo "$CMD"
  echo ""
  echo "Command not executed (dry-run mode). Use --wet-run to execute."
  exit 0
fi

echo "── Encoding (wet-run) ──────────────────────────────────────"
echo ""
echo "$CMD"
echo ""

# Execute
eval "$CMD"

echo ""
echo "── Done ─────────────────────────────────────────────────"
echo "  Output: $OUTPUT"

if [[ "$TRY_MODE" == "true" ]]; then
  echo ""
  echo "  This was a --try encode (5 minutes only)."
  echo "  Review the output quality, then run without --try for the full encode."
fi

# ── Verify streams (if mkvmerge available) ──────────────────────────────────
if command -v mkvmerge &>/dev/null; then
  echo ""
  echo "── Stream Verification ──────────────────────────────────"
  echo ""
  echo "Source:"
  mkvmerge --identify "$INPUT" 2>/dev/null || true
  echo ""
  echo "Output:"
  mkvmerge --identify "$OUTPUT" 2>/dev/null || true
fi
