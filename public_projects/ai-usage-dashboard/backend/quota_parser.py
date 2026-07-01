"""
Parser for AGY quota/limit data.

Queries the local language server (which proxies to Google's internal
Cloud Code API at daily-cloudcode-pa.googleapis.com) to get the same
remaining quota info shown by AGY's /usage command.

The language server exposes a Connect RPC endpoint:
  /exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary
"""
import json
import os
import re
import subprocess
import urllib.request
import ssl
import socket
from datetime import datetime, timezone

# Set socket timeout globally to avoid hangs
socket.setdefaulttimeout(3)

CLOUD_CODE_ENDPOINT = 'https://daily-cloudcode-pa.googleapis.com'
QUOTA_RPC_PATH = '/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary'
_FALLBACK_PORTS = [41969, 36465, 44953]


def _detect_language_server_pids():
    """Find all PIDs for the language server using safe pgrep."""
    for pattern in ('language_server_linux_x64', 'language_server'):
        try:
            out = subprocess.check_output(['pgrep', '-f', pattern], timeout=2)
            pids = [int(p) for p in out.decode().strip().split() if p.isdigit()]
            if pids:
                return pids
        except Exception:
            pass
    return []


def _detect_language_server_ports():
    """Dynamically detect loopback ports matched to the language server PIDs."""
    pids = _detect_language_server_pids()
    if not pids:
        return _FALLBACK_PORTS

    # Find the inodes of all sockets owned by our language server PIDs
    inodes = set()
    for pid in pids:
        try:
            fd_dir = f"/proc/{pid}/fd"
            if os.path.exists(fd_dir):
                for fd in os.listdir(fd_dir):
                    try:
                        link = os.readlink(os.path.join(fd_dir, fd))
                        if link.startswith("socket:["):
                            inodes.add(link[8:-1])
                    except Exception:
                        pass
        except Exception:
            pass

    ports = []
    # Read /proc/net/tcp and tcp6 for listening loopback sockets matching these inodes
    for net_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            if not os.path.exists(net_file):
                continue
            with open(net_file, "r") as f:
                lines = f.readlines()
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 10:
                    state = parts[3]
                    inode = parts[9]
                    # State "0A" is TCP_LISTEN
                    if state == "0A" and inode in inodes:
                        local_addr = parts[1]
                        if ":" in local_addr:
                            ip_hex, port_hex = local_addr.split(":")
                            try:
                                ports.append(int(port_hex, 16))
                            except ValueError:
                                pass
        except Exception:
            pass

    # Use ss -tln (without -p) as fallback
    if not ports:
        try:
            ss_out = subprocess.check_output(['ss', '-tln'], timeout=2).decode('utf-8', errors='ignore')
            for line in ss_out.splitlines():
                parts = line.split()
                for part in parts:
                    if ':' in part:
                        try:
                            p = int(part.split(':')[-1])
                            if p > 1024 and p not in (8000, 9222):
                                ports.append(p)
                        except ValueError:
                            pass
        except Exception:
            pass

    return list(set(ports)) if ports else _FALLBACK_PORTS


def _detect_csrf_token():
    """Detect the dynamic CSRF token from the command line of the language server process."""
    for pid in _detect_language_server_pids():
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
            args = [arg.decode("utf-8", errors="ignore") for arg in cmdline.split(b"\x00") if arg]
            for i, arg in enumerate(args):
                if arg == "--csrf_token" and i + 1 < len(args):
                    return args[i + 1]
        except Exception:
            pass
    return None


def _parse_iso_time(t_str):
    """Calculate remaining seconds until resetTime."""
    if not t_str:
        return 0
    try:
        t_str = t_str.rstrip('Z')
        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = (dt - now).total_seconds()
        return max(0, int(diff))
    except Exception:
        return 0


def _try_connect_rpc(port, csrf_token):
    """Try to call the RetrieveUserQuotaSummary RPC on the given port."""
    # Try HTTP first, then HTTPS if needed
    for proto in ('http', 'https'):
        url = f'{proto}://127.0.0.1:{port}{QUOTA_RPC_PATH}'
        ctx = None
        if proto == 'https':
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url, data=b'{}',
            headers={
                'Content-Type': 'application/json',
                'Connect-Protocol-Version': '1',
                'x-codeium-csrf-token': csrf_token,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception:
            continue
    raise Exception(f"Failed to connect to RPC on port {port}")


def _detect_agy_plan():
    """Get the AGY plan name from the Cloud Code API's loadCodeAssist endpoint."""
    try:
        token_path = os.path.expanduser('~/.gemini/antigravity-cli/antigravity-oauth-token')
        if not os.path.exists(token_path):
            return 'Gemini Code Assist'
        with open(token_path) as f:
            data = json.loads(f.read())
        access_token = data.get('token', {}).get('access_token', '')

        url = 'https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist'
        req = urllib.request.Request(url, data=b'{}',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            })
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())

        # If a paidTier is present, the user has a paid plan available
        paid = body.get('paidTier')
        if paid:
            name = paid.get('name', '')
            # Clean up the name: 'Gemini Code Assist in Google One AI Pro' -> 'Google One AI Pro'
            idx = name.find('in ')
            if idx >= 0:
                return name[idx + 3:].strip()
            return name.strip()

        # Fall back to current tier name
        current = body.get('currentTier', {})
        return current.get('name', 'Gemini Code Assist')
    except Exception:
        return 'Gemini Code Assist'


def fetch_agy_quota():
    """
    Fetch remaining quota from AGY and format it for database storage.

    Returns dict like:
      gemini_models: {
          weekly_limit: {used, total, remaining_pct, refreshes_in},
          five_hour_limit: {used, total, remaining_pct, refreshes_in}
      }
      claude_gpt_models: {
          weekly_limit: {used, total, remaining_pct, refreshes_in},
          five_hour_limit: {used, total, remaining_pct, refreshes_in}
      }
    """
    plan = _detect_agy_plan()
    csrf_token = _detect_csrf_token()
    if not csrf_token:
        return {'error': 'Language server process or CSRF token not found', 'plan': plan}

    raw_data = None
    for port in _detect_language_server_ports():
        try:
            raw_data = _try_connect_rpc(port, csrf_token)
            if raw_data:
                break
        except Exception:
            continue

    if not raw_data or 'response' not in raw_data:
        return {'error': 'Failed to fetch quota from local RPC', 'plan': plan}

    formatted = {}
    try:
        groups = raw_data['response'].get('groups', [])
        for group in groups:
            display_name = group.get('displayName', '')
            if 'gemini' in display_name.lower():
                group_key = 'gemini_models'
            elif 'claude' in display_name.lower() or 'gpt' in display_name.lower():
                group_key = 'claude_gpt_models'
            else:
                group_key = display_name.lower().replace(' ', '_')

            formatted[group_key] = {}
            for bucket in group.get('buckets', []):
                bucket_id = bucket.get('bucketId', '')
                if 'weekly' in bucket_id.lower():
                    limit_key = 'weekly_limit'
                elif '5h' in bucket_id.lower():
                    limit_key = 'five_hour_limit'
                else:
                    limit_key = bucket.get('displayName', '').lower().replace(' ', '_')

                rem_frac = bucket.get('remainingFraction', 0.0)
                refreshes_in = _parse_iso_time(bucket.get('resetTime', ''))

                formatted[group_key][limit_key] = {
                    'used': (1.0 - rem_frac) * 100.0,
                    'total': 100.0,
                    'remaining_pct': rem_frac * 100.0,
                    'refreshes_in': refreshes_in
                }
        formatted['plan'] = plan
        return formatted
    except Exception as e:
        return {'error': f'Failed to parse raw quota data: {e}', 'plan': plan}
