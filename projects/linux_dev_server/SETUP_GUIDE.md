# Linux Dev Server — Manual Setup Guide

Step-by-step instructions for setting up the dev server on your always-on Linux host.
Each step is independent — if something fails, fix it and continue from where you left off.

---

## Prerequisites

| What | Why |
|------|-----|
| A Linux machine (Ubuntu 22.04/24.04 recommended) | Runs the containers 24/7 |
| SSH access to the Linux machine | To run commands remotely |
| An SSH key pair on each client (MacBook, Linux VM) | For passwordless SSH into the dev container |
| An OpenRouter API key | For AI coding agents (Claude Code, OpenCode) |

---

## Step 1: Install Docker

> **Run on:** Linux host

Check if Docker is already installed:

```bash
docker --version
docker compose version
```

If not installed:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

> [!IMPORTANT]
> After adding yourself to the docker group, **log out and back in** (or run `newgrp docker`) for the change to take effect.

**Verify:**

```bash
docker run --rm hello-world
```

You should see "Hello from Docker!" in the output.

---

## Step 2: Copy the project to the host

> **Run on:** MacBook (or wherever this repo lives)

Copy the project files to your Linux host:

```bash
# Replace <HOST_USER> and <HOST_IP> with your values
scp -r ~/dev/projects/linux_dev_server <HOST_USER>@<HOST_IP>:~/dev-services
```

Or, if you prefer Git:

```bash
# On the Linux host
git clone <your-repo-url> ~/dev-services
```

---

## Step 3: Create the `.env` file

> **Run on:** Linux host

```bash
cd ~/dev-services
cp .env.example .env
nano .env    # or vim, whatever you prefer
```

Fill in your actual values:

```ini
# Required — get yours at https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-v1-your-actual-key-here

# Optional — leave blank if not using OpenCode Zen
OPENCODE_ZEN_API_KEY=

# Gitea admin account — pick a secure password
GITEA_ADMIN_USER=dev
GITEA_ADMIN_PASSWORD=pick-a-real-password
GITEA_ADMIN_EMAIL=you@example.com

# Git identity used inside the dev container
GIT_USER_NAME=Your Name
GIT_USER_EMAIL=you@example.com
```

**Verify:**

```bash
cat .env   # Make sure the values look right
```

---

## Step 4: Add your SSH public keys

> **Run on:** MacBook and/or Linux VM

The dev container uses SSH key authentication — no passwords. You need to copy your
public key into the `ssh-keys/` directory on the host.

### From your MacBook:

```bash
# If you don't have an SSH key yet:
ssh-keygen -t ed25519

# Copy your public key to the host
scp ~/.ssh/id_ed25519.pub <HOST_USER>@<HOST_IP>:~/dev-services/ssh-keys/macbook.pub
```

### From a Linux VM (optional second client):

```bash
ssh-keygen -t ed25519    # if needed
scp ~/.ssh/id_ed25519.pub <HOST_USER>@<HOST_IP>:~/dev-services/ssh-keys/linux-vm.pub
```

**Verify (on the Linux host):**

```bash
ls -la ~/dev-services/ssh-keys/
# You should see your .pub file(s) listed
```

---

## Step 5: Find your host IP

> **Run on:** Linux host

```bash
hostname -I | awk '{print $1}'
```

Write this down — you'll need it for the `.bazelrc` and SSH config.

---

## Step 6: Configure the Bazel remote cache address

> **Run on:** Linux host

The `.bazelrc` template has a placeholder for your host IP. Replace it:

```bash
cd ~/dev-services

# Replace HOST_IP_PLACEHOLDER with your actual IP (from Step 5)
sed -i "s|HOST_IP_PLACEHOLDER|YOUR_HOST_IP_HERE|g" dev-container/bazelrc.template
```

**Verify:**

```bash
cat dev-container/bazelrc.template
```

You should see your IP, not `HOST_IP_PLACEHOLDER`:

```
build --bes_results_url=http://192.168.1.100:8080/invocation/
build --bes_backend=grpc://192.168.1.100:1985
build --remote_cache=grpc://192.168.1.100:1985
```

---

## Step 7: Start BuildBuddy

> **Run on:** Linux host

Start BuildBuddy first since the dev container depends on it:

```bash
cd ~/dev-services
docker compose -f server.yml up -d buildbuddy
```

**Verify:**

```bash
# Check it is running
docker compose -f server.yml ps | grep buildbuddy
# Should show "Up"

# Wait a few seconds, then test the web UI
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
# Should return: 200
```

You can also open `http://<HOST_IP>:8080` in your browser to see the BuildBuddy dashboard.

---

## Step 8: Start Gitea

> **Run on:** Linux host

```bash
cd ~/dev-services
docker compose -f server.yml up -d gitea
```

**Verify:**

```bash
# Wait ~30 seconds (Gitea is slower to start), then check health
docker inspect --format='{{.State.Health.Status}}' gitea
# Should say: healthy

# Test the API
curl -s http://localhost:3000/api/v1/version
# Should return something like: {"version":"1.23.x"}
```

You can also open `http://<HOST_IP>:3000` in your browser.

---

## Step 9: Create the Gitea admin user and repository

> **Run on:** Linux host

The Gitea web installer is bypassed (via `INSTALL_LOCK=true`), so you need to create
the admin user via the command line.

### Create admin user:

```bash
# Use the values from your .env file
docker exec -u 1000 gitea gitea admin user create \
    --username dev \
    --password 'your-password-here' \
    --email dev@localhost \
    --admin \
    --must-change-password=false
```

> [!NOTE]
> If you get "user already exists", that's fine — it means you already ran this step.

### Create a repository:

```bash
# Create a repo called "main" (or whatever you want)
curl -X POST "http://localhost:3000/api/v1/user/repos" \
    -H "Content-Type: application/json" \
    -u "dev:your-password-here" \
    -d '{"name": "main", "auto_init": false, "default_branch": "main"}'
```

**Verify:**

Open `http://<HOST_IP>:3000/dev/main` in your browser — you should see the empty repository page.

---

## Step 10: Build and start the dev container

> **Run on:** Linux host

```bash
cd ~/dev-services
docker compose -f server.yml build dev
docker compose -f server.yml up -d dev
```

This will take a few minutes the first time (downloading Ubuntu, Node.js, Bazelisk, etc.).

**Verify:**

```bash
# Check it's running and healthy
docker inspect --format='{{.State.Health.Status}}' dev
# Should say: healthy

# Check all three are running
docker compose -f server.yml ps
```

You should see all three containers with status `Up` and `(healthy)`.

---

## Step 11: Configure Git inside the dev container

> **Run on:** Linux host

```bash
docker exec dev bash -c "
    git config --global user.name 'Your Name' &&
    git config --global user.email 'you@example.com' &&
    cd ~/workspace/main &&
    git init &&
    git remote add origin http://gitea:3000/dev/main.git
"
```

> [!NOTE]
> Inside the Docker network, the dev container reaches Gitea at `gitea:3000` (Docker DNS), not at `<HOST_IP>:3000`.

**Verify:**

```bash
docker exec dev bash -c "cd ~/workspace/main && git remote -v"
# Should show: origin  http://gitea:3000/dev/main.git
```

---

## Step 12: Configure SSH on your MacBook

> **Run on:** MacBook

Add the dev container to your SSH config:

```bash
nano ~/.ssh/config
```

Add this block (replace `<HOST_IP>` with your actual host IP from Step 5):

```
# Dev container on always-on host
Host devserver
  HostName <HOST_IP>
  Port 2220
  User dev
  IdentityFile ~/.ssh/id_ed25519
```

**Verify:**

```bash
ssh devserver "echo 'Connection successful!'"
# Should print: Connection successful!
```

If it doesn't connect, troubleshoot:

```bash
# Verbose SSH to see what's happening
ssh -v devserver

# Check the container logs for SSH errors
ssh <HOST_USER>@<HOST_IP> "docker logs dev"
```

---

## Step 13: Connect Antigravity / Windsurf

> **Run on:** MacBook

1. Open Antigravity (or Windsurf)
2. `Cmd+Shift+P` → **Remote-SSH: Connect to Host**
3. Select devserver
4. Once connected, open folder: `/home/dev/workspace/main`

You're now editing code on your Linux host from your MacBook.

---

## Step 14 (Optional): Set up a Linux VM client

If you also want to code from a Linux VM, run `setup_linux_client.sh` on that machine:

```bash
HOST_IP='<HOST_IP>' HOST_USER='<HOST_USER>' ./setup_linux_client.sh
```

Or follow the same manual steps as Steps 4 and 12 above, adapting for the VM.

---

## Quick Reference

### Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Dev container SSH | `ssh devserver` (port 2220) | Code editing via Antigravity/Windsurf |
| Gitea | `http://<HOST_IP>:3000` | Git web UI, repository management |
| BuildBuddy | `http://<HOST_IP>:8080` | Bazel test results dashboard |

### Common Commands

```bash
# --- All services ---
docker compose -f server.yml up -d          # Start all
docker compose -f server.yml down           # Stop all
docker compose -f server.yml ps             # Status
docker compose -f server.yml logs -f        # Follow logs (all services)
docker compose -f server.yml logs -f dev    # Follow logs (dev only)

# --- Dev container ---
docker compose -f server.yml build dev                   # Rebuild after Dockerfile changes
docker compose -f server.yml up -d dev                   # Restart dev
docker compose -f server.yml restart dev                 # Restart (e.g., after adding SSH keys)
docker exec -it dev bash                   # Shell into the container

# --- Backup ---
# Gitea + BuildBuddy data (bind mounts)
tar czf backup-data.tar.gz gitea/ buildbuddy/

# Dev workspace (named Docker volume)
docker run --rm \
    -v dev-workspace:/data \
    -v $(pwd):/backup \
    busybox tar czf /backup/workspace-backup.tar.gz -C /data .

# --- Adding a new SSH key later ---
cp new-client.pub ~/dev-services/ssh-keys/client-name.pub
cd ~/dev-services && docker compose -f server.yml restart dev
```

### Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't SSH into dev container | Check `ssh-keys/` has your `.pub` file, then `docker compose -f server.yml restart dev` |
| Gitea healthcheck failing | `docker logs gitea` — usually just needs more startup time |
| Bazel can't reach BuildBuddy | Check `.bazelrc` has the correct host IP, and `docker compose -f server.yml ps` shows buildbuddy running |
| Dev container keeps restarting | `docker logs dev` — likely SSH key or sshd config issue |
| Permission denied on data dirs | `sudo chown -R 1000:1000 gitea/ buildbuddy/` |
