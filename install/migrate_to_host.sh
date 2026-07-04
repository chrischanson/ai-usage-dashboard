#!/usr/bin/env bash
#
# migrate_to_host.sh
# Run this script on the Debian VM host to migrate the AI Usage Dashboard
# from the dev container to run natively on the host VM.
#
# Usage:
#   bash migrate_to_host.sh [destination_path]
#
# Example:
#   bash migrate_to_host.sh ~/ai-usage-dashboard
#

set -euo pipefail

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0;37m' # No Color

echo -e "${GREEN}=== AI Usage Dashboard Host Migration Script ===${NC}"

# 1. Verify we are running on the host, not inside a container
if [ -f /.dockerenv ]; then
    echo -e "${RED}Error: This script must be run on the host Debian VM, not inside the Docker container.${NC}"
    echo -e "Please exit the container/SSH session and run it on the host VM."
    exit 1
fi

# 2. Check if docker command is available
if ! command -v docker &>/dev/null; then
    echo -e "${RED}Error: docker command not found on this host.${NC}"
    echo -e "Ensure Docker is installed and your user is in the 'docker' group."
    exit 1
fi

# 3. Check if the dev container is running
if ! docker ps --filter "name=^dev$" --format '{{.Names}}' | grep -q "^dev$"; then
    echo -e "${RED}Error: The 'dev' container is not running.${NC}"
    echo -e "Please start the dev container first: 'docker compose -f ~/dev-services/server.yml up -d dev'"
    exit 1
fi

# 4. Resolve destination path
DEST_DIR="${1:-$HOME/ai-usage-dashboard}"
DEST_DIR="${DEST_DIR/#\~/$HOME}" # Expand leading tilde, if any (no eval — DEST_DIR is user input)
echo -e "Target destination: ${YELLOW}$DEST_DIR${NC}"

if [ -d "$DEST_DIR" ]; then
    echo -e "${YELLOW}Warning: Destination directory $DEST_DIR already exists.${NC}"
    read -p "Do you want to overwrite it? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Migration aborted by user.${NC}"
        exit 1
    fi
    rm -rf "$DEST_DIR"
fi

# 5. Copy files from the dev container
echo -e "Copying dashboard files and SQLite database from container 'dev'..."
mkdir -p "$DEST_DIR"
if ! docker cp dev:/home/dev/workspace/main/public_projects/ai-usage-dashboard/. "$DEST_DIR/"; then
    echo -e "${RED}Error: Failed to copy files from the container.${NC}"
    echo -e "Check if the path '/home/dev/workspace/main/public_projects/ai-usage-dashboard' exists in the container."
    exit 1
fi

echo -e "${GREEN}Files copied successfully!${NC}"

# 6. Verify python3 and venv on host
echo -e "Checking python3 and venv on the host..."
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 is not installed on this host.${NC}"
    echo -e "Please run: sudo apt-get update && sudo apt-get install -y python3 python3-venv"
    exit 1
fi

# Test if python3 can import venv
if ! python3 -c "import venv" &>/dev/null; then
    echo -e "${RED}Error: python3-venv module is missing on this host.${NC}"
    echo -e "Please run: sudo apt-get update && sudo apt-get install -y python3-venv"
    exit 1
fi

# 7. Create virtual environment and install dependencies
echo -e "Creating python virtual environment in ${YELLOW}$DEST_DIR/venv${NC}..."
cd "$DEST_DIR"
python3 -m venv venv
venv/bin/pip install --upgrade pip
echo -e "Installing python packages..."
venv/bin/pip install -r requirements.txt

# 8. Set up permissions
echo -e "Ensuring correct permissions..."
chmod +x run.sh start.sh verify.py
chmod +x install/install.sh install/uninstall.sh

# 9. Verify configurations
echo -e "Verifying dependencies and running local test suite..."
# Run python tests on the host to verify
if PYTHONPATH=backend venv/bin/python3 verify.py; then
    echo -e "${GREEN}Integration tests passed successfully!${NC}"
else
    echo -e "${YELLOW}Warning: Integration tests returned failures/warnings.${NC}"
    echo -e "Ensure your local paths are accessible. (e.g. check permissions on ~/.gemini/ and ~/.codex/)"
    read -p "Do you want to proceed with systemd installation anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 10. Install systemd service
echo -e "Registering systemd service..."
sudo bash install/install.sh "$DEST_DIR" "$USER"

# Start the service
echo -e "Starting the systemd service..."
sudo systemctl start usage-dashboard

# Check status
echo -e "Checking service status..."
sleep 2
if sudo systemctl is-active --quiet usage-dashboard; then
    echo -e "${GREEN}Success! AI Usage Dashboard is running natively on the host.${NC}"
    echo -e "You can access the dashboard locally at: ${YELLOW}http://127.0.0.1:8000${NC}"
    echo -e "To view live logs, run: ${YELLOW}journalctl -u usage-dashboard -f${NC}"
else
    echo -e "${RED}Error: Service failed to start. Run 'journalctl -u usage-dashboard -e' to view logs.${NC}"
    exit 1
fi
