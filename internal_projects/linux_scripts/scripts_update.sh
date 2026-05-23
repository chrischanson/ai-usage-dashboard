#!/bin/bash

# Enclose everything in a main function so the entire script is read into memory
# before execution begins. This makes it safe for the script to update itself
# while running.
main() {
    # Configuration
    GITEA_REPO_URL="http://10.0.0.201:3000/admin/projects.git"
    SCRIPTS_SUBDIR="internal_projects/linux_scripts"
    
    # Define the directory where the script resides
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    
    # Check if we are inside a git repository
    REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"

    if [ -n "$REPO_ROOT" ]; then
        echo "Detected git repository at $REPO_ROOT. Using git pull..."
        cd "$REPO_ROOT" || exit 1
        
        CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
        if [ "$CURRENT_BRANCH" = "HEAD" ]; then
            echo "Warning: You are in a detached HEAD state. Attempting to pull origin main..."
            CURRENT_BRANCH="main"
        fi

        echo "Fetching and pulling latest changes..."
        if git pull origin "$CURRENT_BRANCH" --ff-only; then
            echo "✅ Scripts updated successfully via git pull."
            return 0
        else
            echo "❌ git pull failed. Trying fallback method..."
        fi
    fi

    # Fallback / Standalone mode: Download scripts directly
    echo "Running in standalone mode (not a repo or pull failed)."
    
    if ! command -v git &> /dev/null; then
        echo "Error: 'git' is not installed. Cannot download scripts."
        exit 1
    fi

    TEMP_DIR=$(mktemp -d)
    echo "Cloning repository to temporary directory: $TEMP_DIR"
    
    if git clone --depth 1 "$GITEA_REPO_URL" "$TEMP_DIR"; then
        echo "Copying scripts from $SCRIPTS_SUBDIR to $SCRIPT_DIR..."
        
        # Copy files. For scripts_update.sh itself, unlink it first to avoid
        # in-place overwrite which corrupts the active running file descriptor.
        for file in "$TEMP_DIR/$SCRIPTS_SUBDIR"/*; do
            [ -e "$file" ] || continue
            local fname
            fname="$(basename "$file")"
            if [ "$fname" = "scripts_update.sh" ]; then
                rm -f "$SCRIPT_DIR/$fname"
                cp -fp "$file" "$SCRIPT_DIR/$fname"
            else
                cp -fp "$file" "$SCRIPT_DIR/" 2>/dev/null
            fi
        done
        
        # Also copy the public video-compressor.sh script
        local public_video_compressor="$TEMP_DIR/public_projects/video-compressor/video-compressor.sh"
        if [ -f "$public_video_compressor" ]; then
            echo "Copying video-compressor.sh from public_projects to $SCRIPT_DIR..."
            cp -fp "$public_video_compressor" "$SCRIPT_DIR/"
            
            # Clean up old legacy rip-compressor.sh if it exists in the target directory
            if [ -f "$SCRIPT_DIR/rip-compressor.sh" ]; then
                echo "Removing legacy rip-compressor.sh (replaced by video-compressor.sh)..."
                rm -f "$SCRIPT_DIR/rip-compressor.sh"
            fi
        fi
        
        echo "✅ Scripts updated successfully from Gitea."
    else
        echo "❌ Failed to clone repository from $GITEA_REPO_URL"
        rm -rf "$TEMP_DIR"
        exit 1
    fi

    rm -rf "$TEMP_DIR"
}

main "$@"
