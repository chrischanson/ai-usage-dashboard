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
        
        # Copy all files from the subdirectory to the target directory
        # Using -f to overwrite and -p to preserve permissions
        cp -fp "$TEMP_DIR/$SCRIPTS_SUBDIR"/* "$SCRIPT_DIR/" 2>/dev/null
        
        echo "✅ Scripts updated successfully from Gitea."
    else
        echo "❌ Failed to clone repository from $GITEA_REPO_URL"
        rm -rf "$TEMP_DIR"
        exit 1
    fi

    rm -rf "$TEMP_DIR"
}

main "$@"
