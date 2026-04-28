# dev-container/Dockerfile
# Linux dev environment for remote Antigravity/Windsurf development.
# Contains: SSH server, Bazelisk, Clang/LLVM, Python, Node.js, Git,
#           Claude Code CLI, OpenCode, Codex CLI.
FROM ubuntu:24.04

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000

# ── Base packages ──────────────────────────────────────────────
RUN apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    apt-utils \
    # SSH server (required for Antigravity/Windsurf Remote SSH)
    openssh-server \
    # Build tools
    git curl wget ca-certificates gnupg \
    python3 python3-pip python3-venv \
    build-essential pkg-config \
    libssl-dev \
    clang llvm lld \
    # Utilities
    sudo unzip zip jq \
    && rm -rf /var/lib/apt/lists/*

# ── GitHub CLI (gh) ────────────────────────────────────────────
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 22 (required by Antigravity Server) ────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Claude Code CLI ────────────────────────────────────────────
RUN npm install -g npm@latest \
    && npm install -g @anthropic-ai/claude-code

# ── OpenCode (OpenRouter TUI agent) ────────────────────────────
# Install globally so all users can access it
RUN curl -fsSL https://opencode.ai/install | bash \
    && mv /root/.opencode/bin/opencode /usr/local/bin/ || \
    echo "WARNING: OpenCode install failed — skipping (can install later)"

# ── OpenAI Codex CLI ───────────────────────────────────────────
# Terminal-native AI coding agent by OpenAI.
# Uses OPENAI_API_KEY (can be pointed at OpenRouter via OPENAI_BASE_URL)
RUN npm install -g @openai/codex

# ── Bazelisk (manages Bazel versions automatically) ────────────
# Bazelisk downloads the correct Bazel version based on .bazelversion
# in each project. Falls back to the latest LTS if no file exists.
RUN curl -fsSL -o /usr/local/bin/bazel \
    "https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64" \
    && chmod +x /usr/local/bin/bazel \
    && bazel --version

# ── SSH server config ──────────────────────────────────────────
RUN mkdir -p /var/run/sshd \
    # Harden SSH: key-only auth, no passwords, no root login
    && echo "PubkeyAuthentication yes"      >> /etc/ssh/sshd_config.d/dev.conf \
    && echo "PasswordAuthentication no"     >> /etc/ssh/sshd_config.d/dev.conf \
    && echo "PermitRootLogin no"            >> /etc/ssh/sshd_config.d/dev.conf \
    && echo "PermitEmptyPasswords no"       >> /etc/ssh/sshd_config.d/dev.conf \
    # Allow Antigravity Server and agents to receive env vars over SSH
    && echo "AcceptEnv LANG LC_* BAZEL_* OPENROUTER_API_KEY ANTHROPIC_API_KEY ANTHROPIC_BASE_URL OPENCODE_ZEN_API_KEY OPENCODE_API_KEY OPENAI_API_KEY OPENAI_BASE_URL CODEX_API_KEY" \
       >> /etc/ssh/sshd_config.d/dev.conf

# ── Dev user ───────────────────────────────────────────────────
# Ubuntu 24.04 includes a default 'ubuntu' user at UID 1000.
# Remove it first so we can reuse UID/GID 1000 for our dev user.
RUN userdel -r ubuntu 2>/dev/null || true

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# ── Workspace + Bazel config (as dev user) ─────────────────────
USER $USERNAME

RUN mkdir -p /home/$USERNAME/workspace/main/.vscode

COPY --chown=$USERNAME:$USERNAME bazelrc.template /home/$USERNAME/workspace/main/.bazelrc
COPY --chown=$USERNAME:$USERNAME tasks.json      /home/$USERNAME/workspace/main/.vscode/tasks.json

RUN cd /home/$USERNAME/workspace/main \
    && git config --global user.name "Dev User" \
    && git config --global user.email "dev@localhost" \
    && git config --global init.defaultBranch main \
    && git config --global push.autoSetupRemote true \
    && git init

# ── Entrypoint (must run as root for sshd) ─────────────────────
USER root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
