#!/usr/bin/env bash
# setup_linux_client.sh
# Sets up a Linux VM as a dev client connecting to the shared dev container.
# Run this on the Linux VM.
#
# Usage:
#   HOST_IP='192.168.1.100' \    # IP of the always-on host running the dev container
#   HOST_USER='youruser' \       # SSH user on the always-on host
#   ./setup_linux_client.sh
set -euo pipefail

HOST_IP="${HOST_IP:?Set HOST_IP to the always-on host IP}"
HOST_USER="${HOST_USER:?Set HOST_USER to your SSH user on the host}"
SERVICES_DIR="${SERVICES_DIR:-/home/$HOST_USER/dev-services}"
SSH_KEY="$HOME/.ssh/id_ed25519"

echo "=== [1/4] System packages ==="
sudo apt-get update -q
sudo apt-get install -y curl wget git openssh-client

# ── Node.js 22 (required by Antigravity Server and Windsurf Server) ───
if ! command -v node &>/dev/null || [ "$(node --version | cut -d. -f1 | tr -d v)" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
else
    echo "  Node.js $(node --version) already installed"
fi

echo ""
echo "=== [2/4] SSH key ==="
if [ ! -f "$SSH_KEY" ]; then
    ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "linux-vm-client"
    echo "Generated new SSH key at $SSH_KEY"
else
    echo "SSH key already exists at $SSH_KEY"
fi

echo ""
echo "Copying public key to host at ${HOST_USER}@${HOST_IP}..."
# Copy this VM's public key into the host's ssh-keys directory
# so the dev container entrypoint picks it up
ssh "${HOST_USER}@${HOST_IP}" "mkdir -p ${SERVICES_DIR}/ssh-keys"
scp "${SSH_KEY}.pub" "${HOST_USER}@${HOST_IP}:${SERVICES_DIR}/ssh-keys/linux-vm.pub"

echo "Restarting dev container to load new key..."
ssh "${HOST_USER}@${HOST_IP}" "cd ${SERVICES_DIR} && docker compose restart dev"
echo "Waiting for container to come back up..."
sleep 5

echo ""
echo "=== [3/4] SSH config ==="
SSH_CONFIG="$HOME/.ssh/config"
touch "$SSH_CONFIG"
chmod 600 "$SSH_CONFIG"

if grep -q "Host devserver" "$SSH_CONFIG" 2>/dev/null; then
    echo "SSH config entry for 'devserver' already exists, skipping."
else
    cat >> "$SSH_CONFIG" <<EOF

# Dev container on always-on host
Host devserver
  HostName ${HOST_IP}
  Port 2220
  User dev
  IdentityFile ${SSH_KEY}
  # Forward env vars so AI agents pick up API keys from your local shell
  SendEnv OPENROUTER_API_KEY OPENCODE_ZEN_API_KEY ANTHROPIC_API_KEY
EOF
    echo "Added SSH config entry for 'devserver'"
fi

# Test the connection
echo ""
echo "Testing SSH connection to dev container..."
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new devserver "echo 'Connection successful'"; then
    echo "SSH connection works."
else
    echo "WARNING: SSH connection failed. Check that the host is reachable and the key was accepted."
fi

echo ""
echo "=== [4/4] Install Antigravity and Windsurf ==="
echo ""
echo "  Antigravity is available for Linux at https://antigravity.google/download"
echo "  Windsurf is available for Linux at https://windsurf.com/download"
echo ""
echo "  Both install as .deb packages or AppImage — download and install manually."
echo "  Once installed, connecting to the dev container is the same as on macOS:"
echo ""
echo "  In Antigravity or Windsurf:"
echo "    Ctrl+Shift+P -> 'Remote-SSH: Connect to Host' -> devserver"
echo "    Open folder:   /home/dev/workspace/main"
echo ""

echo ""
echo "========================================"
echo "  Linux VM client setup complete!"
echo "========================================"
echo ""
echo "  Dev container:  ssh devserver"
echo "  Gitea:          http://${HOST_IP}:3000"
echo "  BuildBuddy:     http://${HOST_IP}:8080"
echo ""
echo "  Both Antigravity and Windsurf on this VM will connect"
echo "  to the same shared workspace as your MacBook."
echo "  Changes made from either client are immediately visible"
echo "  to the other via the shared dev-workspace volume."
echo ""
