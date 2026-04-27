#!/usr/bin/env bash
#
# rip-compressor-cursor.sh
#
# Compress DVD/Blu-ray rips "as-is" (no crop/resize/filtering):
# - Video: AV1 (libsvtav1) for best modern compression efficiency
# - Audio:
#   - Stereo (<=2 channels): FLAC (lossless compression)
#   - Multichannel (>2 channels, e.g. 5.1): Opus (compressed)
# - Subtitles: copied as-is (all tracks preserved)
# - Chapters + metadata: preserved
#
# Defaults to DRY RUN (prints commands only).
# Use --wet-run to execute ffmpeg commands.
#
# Usage:
#   ./rip-compressor-cursor.sh [options] <input-file-or-directory>
#
# Options:
#   --try                  Encode first 5 minutes only
#   --crf <0-63>           AV1 CRF (default: 24)
#   --preset <0-13>        SVT-AV1 preset (default: 6)
#   --output-root <dir>    Optional output root (preserves relative structure)
#   --bootstrap            Download static ffmpeg build (BtbN) into ~/.local/share/rip-compressor-cursor/ffmpeg
#   --wet-run              Actually execute commands (default is dry-run)
#   --help                 Show help
#
set -euo pipefail

CRF=24
PRESET=6
TRY_MODE=false
DRY_RUN=true
BOOTSTRAP=false
OUTPUT_ROOT=""
INPUT_PATH=""

FFMPEG_HOME="${HOME}/.local/share/rip-compressor-cursor/ffmpeg"
FFMPEG_BIN=""
FFPROBE_BIN=""

usage() {
  sed -n '1,/^set -euo pipefail/p' "$0" | sed '$d'
  exit 0
}

err() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo "[INFO] $*"
}

bootstrap_ffmpeg() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64) arch="linux64" ;;
    aarch64) arch="linuxarm64" ;;
    *) err "Unsupported architecture for bootstrap: $arch" ;;
  esac

  local url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${arch}-gpl.tar.xz"
  local tmpdir
  tmpdir="$(mktemp -d)"
  local tarball="${tmpdir}/ffmpeg.tar.xz"

  command -v curl >/dev/null 2>&1 || err "curl is required for --bootstrap"

  log "Downloading static ffmpeg from:"
  log "  $url"
  curl -L --progress-bar -o "$tarball" "$url"

  mkdir -p "$FFMPEG_HOME"
  tar -xf "$tarball" -C "$tmpdir" --strip-components=1

  mv -f "${tmpdir}/bin/ffmpeg" "${FFMPEG_HOME}/ffmpeg"
  mv -f "${tmpdir}/bin/ffprobe" "${FFMPEG_HOME}/ffprobe"
  chmod +x "${FFMPEG_HOME}/ffmpeg" "${FFMPEG_HOME}/ffprobe"
  rm -rf "$tmpdir"

  log "Installed:"
  log "  ${FFMPEG_HOME}/ffmpeg"
  log "  ${FFMPEG_HOME}/ffprobe"
}

resolve_ffmpeg() {
  if [[ -x "${FFMPEG_HOME}/ffmpeg" && -x "${FFMPEG_HOME}/ffprobe" ]]; then
    FFMPEG_BIN="${FFMPEG_HOME}/ffmpeg"
    FFPROBE_BIN="${FFMPEG_HOME}/ffprobe"
    return
  fi

  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    FFMPEG_BIN="$(command -v ffmpeg)"
    FFPROBE_BIN="$(command -v ffprobe)"
    return
  fi

  err "ffmpeg/ffprobe not found. Run with --bootstrap."
}

check_ffmpeg_support() {
  local encoders
  encoders="$("$FFMPEG_BIN" -hide_banner -encoders 2>/dev/null || true)"
  local missing=()

  echo "$encoders" | grep -q "libsvtav1" || missing+=("libsvtav1")
  echo "$encoders" | grep -q -E "(^|[[:space:]])flac($|[[:space:]])" || missing+=("flac")
  echo "$encoders" | grep -q "libopus" || missing+=("libopus")

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: ffmpeg is missing required encoders:" >&2
    for e in "${missing[@]}"; do
      echo "  - $e" >&2
    done
    echo "Try running with --bootstrap for a full static build." >&2
    exit 1
  fi
}

is_video_file() {
  local path="$1"
  local lower="${path,,}"
  case "$lower" in
    *.mkv|*.mp4|*.m2ts|*.mts|*.ts|*.avi|*.mov|*.wmv|*.vob|*.mpg|*.mpeg|*.webm|*.iso)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

collect_inputs() {
  local input="$1"
  local -n out_files_ref="$2"

  if [[ -f "$input" ]]; then
    if is_video_file "$input"; then
      out_files_ref+=("$input")
    else
      log "Skipping non-video file: $input"
    fi
    return
  fi

  if [[ -d "$input" ]]; then
    while IFS= read -r -d '' f; do
      out_files_ref+=("$f")
    done < <(find "$input" -type f \
      \( -iname "*.mkv" -o -iname "*.mp4" -o -iname "*.m2ts" -o -iname "*.mts" -o -iname "*.ts" \
         -o -iname "*.avi" -o -iname "*.mov" -o -iname "*.wmv" -o -iname "*.vob" -o -iname "*.mpg" \
         -o -iname "*.mpeg" -o -iname "*.webm" -o -iname "*.iso" \) -print0)
    return
  fi

  err "Input path does not exist: $input"
}

print_cmd() {
  local -a cmd=("$@")
  local rendered=""
  local arg
  for arg in "${cmd[@]}"; do
    rendered+="$(printf '%q ' "$arg")"
  done
  echo "${rendered% }"
}

audio_codec_for_stream() {
  local input="$1"
  local stream_idx="$2"
  local channels
  channels="$("$FFPROBE_BIN" -v error -select_streams "a:${stream_idx}" \
    -show_entries stream=channels -of csv=p=0 "$input" 2>/dev/null || echo "")"

  if [[ -z "$channels" ]]; then
    echo "flac"
    return
  fi

  if (( channels <= 2 )); then
    echo "flac"
  else
    echo "libopus"
  fi
}

build_audio_args() {
  local input="$1"
  local -n out_args_ref="$2"
  local a_count
  a_count="$("$FFPROBE_BIN" -v error -select_streams a \
    -show_entries stream=index -of csv=p=0 "$input" 2>/dev/null | wc -l | tr -d ' ')"

  if [[ -z "$a_count" || "$a_count" == "0" ]]; then
    return
  fi

  local i codec
  for (( i=0; i<a_count; i++ )); do
    codec="$(audio_codec_for_stream "$input" "$i")"
    if [[ "$codec" == "flac" ]]; then
      out_args_ref+=("-c:a:${i}" "flac")
      out_args_ref+=("-compression_level:a:${i}" "8")
    else
      out_args_ref+=("-c:a:${i}" "libopus")
      out_args_ref+=("-b:a:${i}" "320k")
      out_args_ref+=("-vbr:a:${i}" "on")
    fi
  done
}

compute_output_path() {
  local input="$1"
  local root_input="$2"
  local base_name rel_dir output_dir output_file

  base_name="$(basename "${input%.*}")"

  if [[ -n "$OUTPUT_ROOT" ]]; then
    if [[ -d "$root_input" ]]; then
      rel_dir="$(dirname "${input#"$root_input"/}")"
      if [[ "$rel_dir" == "." ]]; then
        output_dir="$OUTPUT_ROOT"
      else
        output_dir="${OUTPUT_ROOT}/${rel_dir}"
      fi
    else
      output_dir="$OUTPUT_ROOT"
    fi
  else
    output_dir="$(dirname "$input")"
  fi

  mkdir -p "$output_dir"
  output_file="${output_dir}/${base_name}-compressed.mkv"
  echo "$output_file"
}

encode_one() {
  local input="$1"
  local root_input="$2"
  local output
  output="$(compute_output_path "$input" "$root_input")"

  local in_real out_real
  in_real="$(readlink -f "$input" 2>/dev/null || echo "$input")"
  out_real="$(readlink -f "$output" 2>/dev/null || echo "$output")"
  [[ "$in_real" == "$out_real" ]] && err "Refusing to overwrite input: $input"

  local -a cmd
  cmd=("$FFMPEG_BIN" "-hide_banner" "-y")

  if [[ "$TRY_MODE" == "true" ]]; then
    cmd+=("-t" "300")
  fi

  cmd+=(
    "-i" "$input"
    "-map" "0"
    "-map_metadata" "0"
    "-map_chapters" "0"
    "-c:v" "libsvtav1"
    "-crf" "$CRF"
    "-preset" "$PRESET"
    "-svtav1-params" "tune=0:film-grain=0"
    "-c:s" "copy"
    "-c:d" "copy"
    "-c:t" "copy"
    "-movflags" "+faststart"
  )

  local -a audio_args=()
  build_audio_args "$input" audio_args
  if [[ ${#audio_args[@]} -gt 0 ]]; then
    cmd+=("${audio_args[@]}")
  fi

  cmd+=("$output")

  echo
  log "Input:  $input"
  log "Output: $output"
  if [[ "$TRY_MODE" == "true" ]]; then
    log "Mode:   TRY (first 5 minutes)"
  else
    log "Mode:   FULL"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "DRY-RUN:"
    print_cmd "${cmd[@]}"
    return 0
  fi

  echo "WET-RUN:"
  print_cmd "${cmd[@]}"
  "${cmd[@]}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --try)
        TRY_MODE=true
        shift
        ;;
      --crf)
        [[ $# -ge 2 ]] || err "--crf requires a value"
        CRF="$2"
        shift 2
        ;;
      --preset)
        [[ $# -ge 2 ]] || err "--preset requires a value"
        PRESET="$2"
        shift 2
        ;;
      --output-root)
        [[ $# -ge 2 ]] || err "--output-root requires a value"
        OUTPUT_ROOT="$2"
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
        err "Unknown option: $1"
        ;;
      *)
        if [[ -n "$INPUT_PATH" ]]; then
          err "Only one input path is supported."
        fi
        INPUT_PATH="$1"
        shift
        ;;
    esac
  done

  [[ -n "$INPUT_PATH" ]] || err "No input path specified. Use --help for usage."
}

validate_numeric_options() {
  [[ "$CRF" =~ ^[0-9]+$ ]] || err "--crf must be an integer"
  [[ "$PRESET" =~ ^[0-9]+$ ]] || err "--preset must be an integer"
  (( CRF >= 0 && CRF <= 63 )) || err "--crf out of range (0-63)"
  (( PRESET >= 0 && PRESET <= 13 )) || err "--preset out of range (0-13)"
}

main() {
  parse_args "$@"
  validate_numeric_options

  if [[ "$BOOTSTRAP" == "true" ]]; then
    bootstrap_ffmpeg
  fi

  resolve_ffmpeg
  check_ffmpeg_support

  local -a files=()
  collect_inputs "$INPUT_PATH" files
  (( ${#files[@]} > 0 )) || err "No supported video files found."

  log "ffmpeg: $FFMPEG_BIN"
  log "ffprobe: $FFPROBE_BIN"
  log "Found ${#files[@]} file(s)."
  [[ "$DRY_RUN" == "true" ]] && log "Dry-run enabled (use --wet-run to execute)."

  local f
  for f in "${files[@]}"; do
    encode_one "$f" "$INPUT_PATH"
  done

  echo
  log "Done."
}

main "$@"
