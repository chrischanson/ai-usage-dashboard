#!/usr/bin/env bash
# entrypoint.sh
# Runs as root. Sets up SSH keys, generates host keys if missing,
# then starts the SSH daemon in the foreground.
set -e

AUTH_KEYS="/home/dev/.ssh/authorized_keys"
KEYS_DIR="/etc/ssh-keys"

# ── SSH host keys ──────────────────────────────────────────────
HOST_KEYS_DIR="/etc/ssh-host-keys"

# 1. Restore keys from persistent volume if they exist
if ls "$HOST_KEYS_DIR"/ssh_host_*_key >/dev/null 2>&1; then
    cp -a "$HOST_KEYS_DIR"/ssh_host_*_key* /etc/ssh/
    chmod 600 /etc/ssh/ssh_host_*_key 2>/dev/null || true
fi

# 2. Generate host keys if they don't exist (first boot of a fresh container)
ssh-keygen -A 2>/dev/null

# 3. Save a copy of the keys back to the persistent volume
cp -a /etc/ssh/ssh_host_*_key* "$HOST_KEYS_DIR/"

# ── Client public keys ────────────────────────────────────────
mkdir -p /home/dev/.ssh
chmod 700 /home/dev/.ssh

# Clear and rebuild authorized_keys from all mounted public keys
if [ -d "$KEYS_DIR" ] && compgen -G "$KEYS_DIR/*.pub" > /dev/null; then
    cat "$KEYS_DIR"/*.pub > "$AUTH_KEYS"
    KEY_COUNT=$(ls "$KEYS_DIR"/*.pub | wc -l)
    echo "[entrypoint] Loaded $KEY_COUNT SSH public key(s) from $KEYS_DIR"
else
    echo "[entrypoint] WARNING: No *.pub files found in $KEYS_DIR"
    echo "             No clients will be able to connect."
    echo "             Add public key files to ./ssh-keys/ on the host and restart."
    touch "$AUTH_KEYS"
fi

chmod 600 "$AUTH_KEYS"
chown -R dev:dev /home/dev/.ssh

# ── Export environment variables for SSH sessions ─────────────
# SSH strips Docker env vars upon login. We must explicitly write 
# the AI keys into a profile script so the dev user has access.
cat <<EOF > /etc/profile.d/ai-keys.sh
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN}"
export ANTHROPIC_API_KEY=""
export ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL}"
export CLAUDE_CODE_SUBAGENT_MODEL="${CLAUDE_CODE_SUBAGENT_MODEL}"
export OPENAI_API_BASE="${OPENAI_API_BASE}"
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export OPENCODE_API_KEY="${OPENCODE_API_KEY}"
export OPENCODE_ZEN_API_KEY="${OPENCODE_ZEN_API_KEY}"
export CODEX_API_KEY="${CODEX_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL}"
# When Codex is pointed at real OpenAI, make OPENAI_API_KEY match
# CODEX_API_KEY so Codex picks up the right key.
if [ -n "${CODEX_API_KEY}" ] && [ "${OPENAI_BASE_URL}" != "https://openrouter.ai/api/v1" ]; then
  export OPENAI_API_KEY="${CODEX_API_KEY}"
fi
EOF

# Also write to ~/.bashrc so non-login interactive shells (VS Code terminal,
# docker exec bash) have access. Use a marker so we can append on restart.
BASHRC="/home/dev/.bashrc"
MARKER="# >>> ai-keys >>>"
if ! grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
    cat <<EOF >> "$BASHRC"

$MARKER
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN}"
export ANTHROPIC_API_KEY=""
export ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL}"
export CLAUDE_CODE_SUBAGENT_MODEL="${CLAUDE_CODE_SUBAGENT_MODEL}"
export OPENAI_API_BASE="${OPENAI_API_BASE}"
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export OPENCODE_API_KEY="${OPENCODE_API_KEY}"
export OPENCODE_ZEN_API_KEY="${OPENCODE_ZEN_API_KEY}"
export CODEX_API_KEY="${CODEX_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL}"
# When Codex is pointed at real OpenAI, make OPENAI_API_KEY match
# CODEX_API_KEY so Codex picks up the right key.
if [ -n "${CODEX_API_KEY}" ] && [ "${OPENAI_BASE_URL}" != "https://openrouter.ai/api/v1" ]; then
  export OPENAI_API_KEY="${CODEX_API_KEY}"
fi
# <<< ai-keys <<<
EOF
    chown dev:dev "$BASHRC"
fi

# ── Startup banner ────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Dev container ready"
echo "  SSH listening on port 22"
echo "  User: dev"
echo "  Workspace: /home/dev/workspace/main"
echo "============================================"
echo ""

# ── Start SSH daemon ──────────────────────────────────────────
# Run in foreground (-D) so the container stays alive.
# Use exec so sshd becomes PID 1 and receives signals properly.
exec /usr/sbin/sshd -D -e
