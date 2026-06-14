#!/bin/bash

# Exit on error
set -e

CLI_DIR="$HOME/.gemini/antigravity-cli"
IDE_DIR="$HOME/.gemini/antigravity-ide"
BACKUP_DIR="$HOME/.gemini/antigravity_backup_$(date +%Y%m%d_%H%M%S)"

echo "=== Antigravity Session Sync Setup ==="

# Check if agy or ide processes are running
if pgrep -f "agy" > /dev/null || pgrep -f "antigravity-ide" > /dev/null; then
  echo "WARNING: Antigravity CLI or IDE processes appear to be running."
  echo "Please close all active Antigravity CLI terminals and IDE windows before running this script."
  read -p "Do you want to proceed anyway? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi

# Create backup directory
echo "Creating backup at: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
cp -r "$CLI_DIR/brain" "$BACKUP_DIR/brain" 2>/dev/null || true
cp -r "$CLI_DIR/conversations" "$BACKUP_DIR/conversations" 2>/dev/null || true
cp -r "$IDE_DIR/brain" "$BACKUP_DIR/ide_brain" 2>/dev/null || true
cp -r "$IDE_DIR/conversations" "$BACKUP_DIR/ide_conversations" 2>/dev/null || true

# Copy existing CLI brains and conversations to IDE (merging them)
echo "Merging existing CLI history into IDE directory..."
mkdir -p "$IDE_DIR/brain" "$IDE_DIR/conversations"
cp -rn "$CLI_DIR/brain/"* "$IDE_DIR/brain/" 2>/dev/null || true
cp -rn "$CLI_DIR/conversations/"* "$IDE_DIR/conversations/" 2>/dev/null || true

# Remove CLI directories
echo "Removing old CLI folders..."
rm -rf "$CLI_DIR/brain"
rm -rf "$CLI_DIR/conversations"

# Create symbolic links
echo "Creating symbolic links..."
ln -s "$IDE_DIR/brain" "$CLI_DIR/brain"
ln -s "$IDE_DIR/conversations" "$CLI_DIR/conversations"

echo "Success! Your CLI and IDE sessions are now shared."
