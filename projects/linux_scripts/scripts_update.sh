#!/bin/bash

# Enclose everything in a main function so the entire script is read into memory
# before execution begins. This makes it safe for the script to update itself
# while running.
main() {
    # Define the directory where the script resides
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

    # Find the root of the git repository
    REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"

    if [ -z "$REPO_ROOT" ]; then
        echo "Error: Not running inside a git repository."
        exit 1
    fi

    echo "Changing directory to repository root: $REPO_ROOT"
    cd "$REPO_ROOT" || exit 1

    # Check current branch
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

    if [ "$CURRENT_BRANCH" = "HEAD" ]; then
        echo "Warning: You are in a detached HEAD state. Cannot auto-update."
        exit 1
    fi

    echo "Fetching latest changes from Gitea server (origin)..."
    git fetch origin

    echo "Pulling latest changes for branch '$CURRENT_BRANCH'..."
    # Using --ff-only to avoid accidental merge commits during auto-update.
    # If there are local changes, it will fail gracefully instead of creating a merge conflict.
    if git pull origin "$CURRENT_BRANCH" --ff-only; then
        echo "✅ Scripts updated successfully."
    else
        echo "❌ Failed to update automatically. You may have local changes or diverged branches."
        echo "Please resolve manually."
        exit 1
    fi
}

main "$@"
