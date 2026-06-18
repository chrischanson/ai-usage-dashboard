# dev-container/Dockerfile
# Linux dev environment for remote Antigravity/Windsurf development.
# Contains: SSH server, Bazelisk, Clang/LLVM, Python, Node.js, Git,
#           Claude Code CLI, OpenCode, Codex CLI.
FROM ubuntu:24.04

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000
 
# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# ── Base packages ──────────────────────────────────────────────
RUN apt-get update -q && apt-get install -y --no-install-recommends \
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
    sudo unzip zip jq tmux \
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

# ── Claude Code CLI dependencies ────────────────────────────────
# NodeSource .deb ships a broken npm (missing promise-retry); use corepack
# to upgrade npm instead of the broken npm trying to upgrade itself.
RUN corepack enable \
    && corepack prepare npm@latest --activate

# ── Bazelisk (manages Bazel versions automatically) ────────────
# Bazelisk downloads the correct Bazel version based on .bazelversion
# in each project. Falls back to the latest LTS if no file exists.
RUN curl -fsSL -o /usr/local/bin/bazel \
    "https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64" \
    && chmod +x /usr/local/bin/bazel \
    && bazel --version

# ── Tailscale (mesh networking) ───────────────────────────────
RUN curl -fsSL https://tailscale.com/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

# ── SSH server config ──────────────────────────────────────────
RUN mkdir -p /var/run/sshd \
    # Harden SSH: key-only auth, no passwords, no root login
    && echo "PubkeyAuthentication yes"      >> /etc/ssh/sshd_config.d/dev.conf \
    && echo "PasswordAuthentication no"     >> /etc/ssh/sshd_config.d/dev.conf \
    && echo "PermitRootLogin no"            >> /etc/ssh/sshd_config.d/dev.conf \
    && echo "PermitEmptyPasswords no"       >> /etc/ssh/sshd_config.d/dev.conf \
    # Allow Antigravity Server and agents to receive env vars over SSH
    && echo "AcceptEnv LANG LC_* BAZEL_* OPENROUTER_API_KEY ANTHROPIC_API_KEY ANTHROPIC_BASE_URL OPENCODE_ZEN_API_KEY OPENCODE_API_KEY OPENAI_API_KEY OPENAI_BASE_URL CODEX_API_KEY GEMINI_API_KEY" \
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
    && git config --global credential.helper 'store --file /home/dev/workspace/.git-credentials' \
    && git init

# ── AI Coding Tools (Installed inside persistent home volume) ──
ENV PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:/home/dev/.opencode/bin:${PATH}"

RUN mkdir -p /home/dev/.npm-global \
    && npm config set prefix "/home/dev/.npm-global" \
    && npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli

RUN LATEST_VERSION=$(curl -sI https://github.com/anomalyco/opencode/releases/latest | grep -i "location:" | sed -n 's/.*\/tag\/v\([0-9.]*\).*/\1/p' | tr -d '\r') \
    && curl -fsSL https://opencode.ai/install | bash -s -- "$LATEST_VERSION" || \
    echo "WARNING: OpenCode install failed — skipping (can install later)"

RUN curl -fsSL https://antigravity.google/cli/install.sh | bash || \
    echo "WARNING: Antigravity CLI install failed — skipping"

# ── Entrypoint (must run as root for sshd) ─────────────────────
USER root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
