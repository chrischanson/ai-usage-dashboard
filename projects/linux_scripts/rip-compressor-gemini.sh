#!/bin/bash

# Rip Compressor - Gemini Edition
# Compresses DVD/Bluray rips with high quality settings.
# Requirements met:
# 1. No cropping/changes to video layout.
# 2. All subtitles preserved.
# 3. Stereo losslessly compressed (FLAC). 5.1 compressed (Opus).
# 4. Best codec (HEVC/libx265 for video, Opus for 5.1, FLAC for stereo).
# 5. FFmpeg checked for codec support; downloads static build if needed.
# 6. Try mode (-t/--try) converts 5 mins.
# 7. Default dry run; --wet-run executes.
# 8. Takes a folder, recursive search.
# 9. Chapters preserved.

WET_RUN=0
TRY_MODE=0
INPUT_PATH=""

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --wet-run) WET_RUN=1 ;;
        --try|-t) TRY_MODE=1 ;;
        *) 
            if [[ -z "$INPUT_PATH" ]]; then
                INPUT_PATH="$1"
            else
                echo "Unknown parameter: $1"
                exit 1
            fi
            ;;
    esac
    shift
done

if [[ -z "$INPUT_PATH" ]]; then
    echo "Usage: $0 [--wet-run] [--try] <input_file_or_directory>"
    exit 1
fi

# Ensure ffmpeg with libx265 and libopus is available
FFMPEG_BIN="ffmpeg"
FFPROBE_BIN="ffprobe"

if ! command -v ffmpeg >/dev/null 2>&1 || ! ffmpeg -version 2>&1 | grep -q "libx265" || ! ffmpeg -version 2>&1 | grep -q "libopus"; then
    echo "System FFmpeg missing or lacks required codecs (libx265, libopus). Using static build..."
    FFMPEG_DIR="$HOME/.local/bin/ffmpeg-rip-compressor"
    FFMPEG_BIN="$FFMPEG_DIR/ffmpeg"
    FFPROBE_BIN="$FFMPEG_DIR/ffprobe"
    
    if [[ ! -x "$FFMPEG_BIN" ]]; then
        echo "Downloading ffmpeg static build from johnvansickle.com..."
        mkdir -p "$FFMPEG_DIR"
        # Download and extract the latest amd64 static build
        if ! wget -qO- "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" | tar xJ -C "$FFMPEG_DIR" --strip-components=1; then
            echo "Error downloading or extracting FFmpeg. Please check your internet connection."
            exit 1
        fi
    fi
fi

process_file() {
    local input_file="$1"
    
    # Skip already compressed files
    if [[ "$input_file" == *"-compressed.mkv" ]] || [[ "$input_file" == *"-compressed-try.mkv" ]]; then
        return
    fi
    
    local output_file="${input_file%.*}-compressed.mkv"
    
    echo "========================================"
    echo "Processing: $input_file"
    
    local cmd=("$FFMPEG_BIN" -y -i "$input_file")
    
    if [[ $TRY_MODE -eq 1 ]]; then
        cmd+=("-t" "300")
        output_file="${input_file%.*}-compressed-try.mkv"
    fi
    
    # Video: copy as is structurally (no crop), compress with HEVC
    # crf 18 is visually transparent, preset slow for better compression efficiency
    cmd+=("-map" "0:v" "-c:v" "libx265" "-preset" "slow" "-crf" "18")
    
    # Subtitles and Attachments: preserved
    cmd+=("-map" "0:s?" "-c:s" "copy")
    cmd+=("-map" "0:t?" "-c:t" "copy")
    
    # Chapters and Metadata: preserved
    cmd+=("-map_chapters" "0" "-map_metadata" "0")
    
    # Audio processing
    local audio_streams
    # Get audio streams index and channels
    audio_streams=$("$FFPROBE_BIN" -v error -select_streams a -show_entries stream=index,channels -of csv=p=0 "$input_file")
    
    local stream_index=0
    if [[ -n "$audio_streams" ]]; then
        while IFS=',' read -r index channels; do
            # Remove any whitespace or carriage returns
            index=$(echo "$index" | tr -d ' \r')
            channels=$(echo "$channels" | tr -d ' \r')
            
            # Map the stream
            cmd+=("-map" "0:$index")
            
            # Determine codec based on channels
            if [[ "$channels" == "2" ]]; then
                # Stereo -> Lossless (FLAC)
                cmd+=("-c:a:$stream_index" "flac")
            elif [[ "$channels" =~ ^[0-9]+$ ]] && [[ "$channels" -ge 6 ]]; then
                # 5.1 or 7.1 -> Compressed (Opus)
                cmd+=("-c:a:$stream_index" "libopus" "-b:a:$stream_index" "384k")
            else
                # Other channel layouts (Mono, etc) -> Compressed (Opus)
                cmd+=("-c:a:$stream_index" "libopus" "-b:a:$stream_index" "128k")
            fi
            
            ((stream_index++))
        done <<< "$audio_streams"
    fi
    
    cmd+=("$output_file")
    
    if [[ $WET_RUN -eq 1 ]]; then
        echo "Executing command:"
        printf "'%s' " "${cmd[@]}"
        echo ""
        "${cmd[@]}"
    else
        echo "[DRY RUN] Would execute:"
        printf "'%s' " "${cmd[@]}"
        echo ""
        echo "Run with --wet-run to execute."
    fi
    echo "========================================"
}

if [[ -d "$INPUT_PATH" ]]; then
    # Recursively find common video formats
    find "$INPUT_PATH" -type f \( -iname \*.mkv -o -iname \*.mp4 -o -iname \*.avi -o -iname \*.m4v -o -iname \*.ts -o -iname \*.vob -o -iname \*.mov -o -iname \*.m2ts -o -iname \*.wmv \) -print0 | while IFS= read -r -d '' file; do
        process_file "$file"
    done
elif [[ -f "$INPUT_PATH" ]]; then
    process_file "$INPUT_PATH"
else
    echo "Error: '$INPUT_PATH' is not a valid file or directory."
    exit 1
fi
