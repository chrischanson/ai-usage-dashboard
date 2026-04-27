#!/usr/bin/env bash
# =============================================================================
# compress_disc_rip.sh
# Compress DVD/Blu-ray rips with AV1 video, lossless audio, all subtitles
# Dependencies: ffmpeg (with SVT-AV1 support), mediainfo (optional, for info)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these defaults or override via env vars
# ---------------------------------------------------------------------------
CRF="${CRF:-22}"                     # AV1 CRF: 0 (lossless) – 63; lower = better quality
PRESET="${PRESET:-6}"                # SVT-AV1 preset: 0 (slowest/best) – 13 (fastest)
                                     # 4–6 recommended for quality; 8–10 for speed
AUDIO_CODEC="${AUDIO_CODEC:-flac}"   # lossless: flac | truehd | copy (pass through as-is)
                                     # Use 'copy' to keep original bitstream untouched
THREADS="${THREADS:-0}"              # 0 = auto-detect
CONTAINER="${CONTAINER:-mkv}"        # mkv supports everything; mp4 has subtitle limits
TRY_MODE="${TRY_MODE:-false}"        # encode only a short sample when true
TRY_DURATION="${TRY_DURATION:-300}"  # sample length in seconds (default: 5 min)
TRY_START="${TRY_START:-60}"         # start offset in seconds (skip intros/menus)

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()   { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
info()  { echo -e "${CYAN}[    ]${NC}  $*"; }

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    echo -e "
${BOLD}Usage:${NC}
  $0 [OPTIONS] <input_file_or_dir> [input_file_or_dir ...]

${BOLD}Options:${NC}
  -c, --crf <0-63>       AV1 CRF quality (default: ${CRF})
  -p, --preset <0-13>    SVT-AV1 preset speed (default: ${PRESET})
  -a, --audio <codec>    Audio codec: flac | copy (default: ${AUDIO_CODEC})
  -t, --threads <n>      CPU threads, 0=auto (default: ${THREADS})
  -m, --container <ext>  Container: mkv | mp4 (default: ${CONTAINER})
      --try              Encode only a 5-minute sample (try mode)
      --try-duration <s> Sample length in seconds (default: ${TRY_DURATION})
      --try-start <s>    Sample start offset in seconds (default: ${TRY_START})
  -h, --help             Show this help

${BOLD}Examples:${NC}
  # Compress a single file with defaults
  $0 movie.mkv

  # High quality, slow encode, copy audio bitstream
  $0 --crf 20 --preset 4 --audio copy bluray_rip.mkv

  # Batch compress a whole folder (output sits alongside each source file)
  $0 /mnt/rips/

  # Fast preview encode
  CRF=35 PRESET=10 $0 test.mkv

  # Try mode — encode 5 min sample to check quality/size before committing
  $0 --try movie.mkv

  # Try mode with custom window: 3 min starting at 10 min into the film
  $0 --try --try-start 600 --try-duration 180 movie.mkv

${BOLD}Notes:${NC}
  - All subtitle tracks (PGS, SRT, ASS, VOBsub, etc.) are preserved as-is
  - Audio: 'flac' re-encodes to FLAC (lossless); 'copy' passes through DTS-MA, TrueHD, etc.
  - AV1 (SVT-AV1) requires ffmpeg built with --enable-libsvtav1
  - MKV container is strongly recommended for Blu-ray (supports PGS, TrueHD, etc.)
  - MP4 does NOT support PGS subtitles or TrueHD audio — use MKV for those
"
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
INPUTS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--crf)       CRF="$2";       shift 2 ;;
        -p|--preset)    PRESET="$2";    shift 2 ;;
        -a|--audio)     AUDIO_CODEC="$2"; shift 2 ;;
        -t|--threads)   THREADS="$2";   shift 2 ;;
        -m|--container) CONTAINER="$2"; shift 2 ;;
        --try)          TRY_MODE=true; shift ;;
        --try-duration) TRY_DURATION="$2"; shift 2 ;;
        --try-start)    TRY_START="$2"; shift 2 ;;
        -h|--help)      usage ;;
        -*)             error "Unknown option: $1" ;;
        *)              INPUTS+=("$1"); shift ;;
    esac
done

[[ ${#INPUTS[@]} -eq 0 ]] && usage

# ---------------------------------------------------------------------------
# Static ffmpeg download (johnvansickle.com builds — always up to date)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_FFMPEG_DIR="${SCRIPT_DIR}"
STATIC_FFMPEG="${STATIC_FFMPEG_DIR}/ffmpeg"
FFMPEG_BIN="ffmpeg"   # will be overridden to static path if needed

fetch_static_ffmpeg() {
    local arch
    arch="$(uname -m)"

    # BtbN/FFmpeg-Builds: daily auto-builds, includes libsvtav1, GPLv3
    # https://github.com/BtbN/FFmpeg-Builds
    local base="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
    local filename url
    case "$arch" in
        x86_64)  filename="ffmpeg-master-latest-linux64-gpl.tar.xz" ;;
        aarch64) filename="ffmpeg-master-latest-linuxarm64-gpl.tar.xz" ;;
        *)       error "No BtbN static ffmpeg build available for architecture: $arch" ;;
    esac
    url="${base}/${filename}"

    log "Downloading static ffmpeg (${arch}) from BtbN/FFmpeg-Builds ..."
    log "URL: ${url}"

    if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
        error "Neither curl nor wget found — cannot download ffmpeg. Install one first."
    fi

    mkdir -p "$STATIC_FFMPEG_DIR"
    local tarball="${STATIC_FFMPEG_DIR}/ffmpeg-static.tar.xz"

    if command -v curl &>/dev/null; then
        curl -L --progress-bar -o "$tarball" "$url"
    else
        wget -q --show-progress -O "$tarball" "$url"
    fi

    log "Extracting ..."
    # BtbN tarball layout: ffmpeg-master-latest-linux64-gpl/bin/ffmpeg
    local ffmpeg_entry
    ffmpeg_entry="$(tar -tf "$tarball" | grep -E 'bin/ffmpeg$' | head -1)"

    if [[ -z "$ffmpeg_entry" ]]; then
        rm -f "$tarball"
        error "Could not locate ffmpeg binary inside tarball."
    fi

    tar -xf "$tarball" -C "$STATIC_FFMPEG_DIR" \
        --strip-components=2 \
        "$ffmpeg_entry"

    rm -f "$tarball"

    if [[ ! -x "$STATIC_FFMPEG" ]]; then
        error "Extraction failed — ffmpeg binary not found at: $STATIC_FFMPEG"
    fi

    log "Static ffmpeg installed to: $STATIC_FFMPEG"
    log "Version: $("$STATIC_FFMPEG" -version 2>&1 | head -1)"
}

# ---------------------------------------------------------------------------
# Dependency check — auto-downloads static ffmpeg if system build lacks SVT-AV1
# ---------------------------------------------------------------------------
check_deps() {
    # Check if a previously downloaded static build exists and has SVT-AV1
    if [[ -x "$STATIC_FFMPEG" ]]; then
        local enc
        enc="$("$STATIC_FFMPEG" -hide_banner -encoders 2>/dev/null || true)"
        if echo "$enc" | grep -q "libsvtav1"; then
            FFMPEG_BIN="$STATIC_FFMPEG"
            log "Using cached static ffmpeg: $STATIC_FFMPEG ✓"
            return 0
        else
            warn "Cached static ffmpeg lacks SVT-AV1 — re-downloading ..."
            rm -f "$STATIC_FFMPEG"
        fi
    fi

    # Check system ffmpeg
    if command -v ffmpeg &>/dev/null; then
        local sysenc
        sysenc="$(ffmpeg -hide_banner -encoders 2>/dev/null || true)"
        if echo "$sysenc" | grep -q "libsvtav1"; then
            FFMPEG_BIN="ffmpeg"
            log "System ffmpeg has SVT-AV1 support ✓"
            return 0
        else
            warn "System ffmpeg ($(ffmpeg -version 2>&1 | head -1)) lacks libsvtav1."
            warn "The Debian ffmpeg package is often built without it."
        fi
    else
        warn "ffmpeg not found on PATH."
    fi

    # Neither works — offer to download static build
    echo -e "${YELLOW}[WARN]${NC}  A static ffmpeg build with full codec support will be downloaded."
    echo -e "${YELLOW}[WARN]${NC}  Install location: ${STATIC_FFMPEG_DIR}"
    echo -n "        Download now? [Y/n] "
    read -r answer
    case "${answer,,}" in
        n|no) error "Cannot proceed without ffmpeg+SVT-AV1. Aborting." ;;
        *)    fetch_static_ffmpeg ;;
    esac

    local encoders
    encoders="$("$STATIC_FFMPEG" -hide_banner -encoders 2>/dev/null || true)"
    if ! echo "$encoders" | grep -q "libsvtav1"; then
        warn "Encoder list from downloaded binary:"
        echo "$encoders" | grep -i "av1\|svt" || true
        error "Downloaded ffmpeg lacks libsvtav1. Try deleting ${STATIC_FFMPEG} and re-running."
    fi

    FFMPEG_BIN="$STATIC_FFMPEG"
    log "Static ffmpeg ready ✓"
}

# ---------------------------------------------------------------------------
# Probe: collect subtitle and audio stream maps
# ---------------------------------------------------------------------------
get_stream_args() {
    local input="$1"

    # Map ALL streams: video, audio, subtitles, attachments (fonts)
    # -map 0 copies everything; we then override video/audio codecs selectively
    echo "-map 0"
}

get_subtitle_codec_args() {
    local input="$1"
    local container="$2"

    if [[ "$container" == "mp4" ]]; then
        # MP4 only supports MOV_TEXT subtitles; warn user
        warn "MP4 container has limited subtitle support — only text subs (SRT/ASS→mov_text) work."
        warn "PGS/VOBsub image-based subtitles will be DROPPED. Use MKV to keep all subs."
        echo "-c:s mov_text"
    else
        # MKV: copy all subtitle streams as-is (PGS, ASS, SRT, VOBsub all pass through)
        echo "-c:s copy"
    fi
}

get_audio_codec_args() {
    local codec="$1"
    case "$codec" in
        flac)
            # FLAC is lossless and widely compatible; good for archival
            echo "-c:a flac -compression_level 8"
            ;;
        copy)
            # Pass through TrueHD, DTS-MA, etc. byte-for-byte — zero quality loss
            echo "-c:a copy"
            ;;
        *)
            error "Unknown audio codec: $codec. Use 'flac' or 'copy'."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Encode one file
# ---------------------------------------------------------------------------
encode_file() {
    local input="$1"
    local input_dir input_stem
    input_dir="$(dirname "$input")"
    input_stem="$(basename "${input%.*}")"

    # In try mode: append .try suffix and a note about the sample window
    local try_args=()
    local try_suffix=""
    if [[ "$TRY_MODE" == "true" ]]; then
        try_suffix=".try"
        try_args=(-ss "$TRY_START" -t "$TRY_DURATION")
        local start_min=$(( TRY_START / 60 ))
        local start_sec=$(( TRY_START % 60 ))
        local dur_min=$(( TRY_DURATION / 60 ))
        local dur_sec=$(( TRY_DURATION % 60 ))
    fi

    local output="${input_dir}/${input_stem}${try_suffix}.${CONTAINER}"

    if [[ -f "$output" ]]; then
        warn "Output already exists, skipping: $output"
        return 0
    fi

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "Input:   $input"
    log "Output:  $output"
    info "Video:   AV1 (SVT-AV1) | CRF=${CRF} | preset=${PRESET}"
    info "Audio:   ${AUDIO_CODEC}"
    info "Subs:    all tracks preserved"
    if [[ "$TRY_MODE" == "true" ]]; then
        info "TRY:     ${dur_min}m${dur_sec}s sample starting at ${start_min}m${start_sec}s ⚑"
    fi
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    local stream_args sub_codec_args audio_codec_args
    stream_args=$(get_stream_args "$input")
    sub_codec_args=$(get_subtitle_codec_args "$input" "$CONTAINER")
    audio_codec_args=$(get_audio_codec_args "$AUDIO_CODEC")

    # SVT-AV1 tuning params:
    #   tune=0        → visual quality (PSNR)
    #   film-grain=0  → no artificial grain injection (preserve source)
    local svtav1_params="preset=${PRESET}:tune=0:film-grain=0"

    # Build and run ffmpeg command
    # shellcheck disable=SC2086
    "$FFMPEG_BIN" \
        -hide_banner \
        "${try_args[@]+"${try_args[@]}"}" \
        -i "$input" \
        $stream_args \
        -c:v libsvtav1 \
        -crf "$CRF" \
        -svtav1-params "$svtav1_params" \
        -threads "$THREADS" \
        $audio_codec_args \
        $sub_codec_args \
        -disposition:s default \
        -movflags +faststart \
        "$output" \
        && log "Done: $output ✓" \
        || error "Encoding failed for: $input"
}

# ---------------------------------------------------------------------------
# Collect input files (file or directory)
# ---------------------------------------------------------------------------
collect_files() {
    local input="$1"
    local -n _files="$2"

    if [[ -f "$input" ]]; then
        _files+=("$input")
    elif [[ -d "$input" ]]; then
        while IFS= read -r -d '' f; do
            _files+=("$f")
        done < <(find "$input" -maxdepth 2 -type f \
            \( -iname "*.mkv" -o -iname "*.mp4" -o -iname "*.avi" \
               -o -iname "*.m2ts" -o -iname "*.ts" -o -iname "*.vob" \
               -o -iname "*.iso" \) \
            -print0 | sort -z)
    else
        warn "Not a file or directory, skipping: $input"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    check_deps

    local all_files=()
    for inp in "${INPUTS[@]}"; do
        collect_files "$inp" all_files
    done

    if [[ ${#all_files[@]} -eq 0 ]]; then
        error "No supported video files found in the provided inputs."
    fi

    log "Found ${#all_files[@]} file(s) to encode"
    if [[ "$TRY_MODE" == "true" ]]; then
        warn "TRY MODE: encoding ${TRY_DURATION}s sample from offset ${TRY_START}s — output filenames get a .try suffix"
    fi

    local success=0 fail=0
    for f in "${all_files[@]}"; do
        if encode_file "$f"; then
            (( success++ )) || true
        else
            (( fail++ )) || true
            warn "Failed: $f"
        fi
    done

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "Complete: ${success} succeeded, ${fail} failed"
    [[ $fail -gt 0 ]] && exit 1 || exit 0
}

main