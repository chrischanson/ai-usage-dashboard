"""
Parser for AGY quota/limit data.

Queries the local language server (which proxies to Google's internal
Cloud Code API at daily-cloudcode-pa.googleapis.com) to get the same
remaining quota info shown by AGY's /usage command.

The language server exposes a Connect RPC endpoint:
  /exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary
"""
import ipaddress
import json
import os
import re
import socket
import struct
import subprocess
import urllib.request
import ssl
from datetime import datetime, timezone

# No socket.setdefaulttimeout() here: that was a process-global side effect
# that capped every socket opened anywhere in the process (including
# unrelated code) just because this module got imported. Every network call
# below sets its own explicit per-call timeout instead.

CLOUD_CODE_ENDPOINT = 'https://daily-cloudcode-pa.googleapis.com'
QUOTA_RPC_PATH = '/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary'

# Executable name *prefixes* that serve the quota RPC. Matched against a
# candidate process's real executable (/proc/<pid>/exe) or its kernel `comm`,
# never against its command line -- see _detect_language_server_pids.
#
# Prefixes, not exact names, because the installed binaries vary by edition:
#   /opt/antigravity/Antigravity-x64/antigravity
#   /opt/antigravity-ide/Antigravity-IDE/antigravity-ide
#   /opt/antigravity/Antigravity-x64/resources/bin/language_server
#   ~/.local/bin/agy
# An exact-name list rejected `antigravity-ide` outright.
_LS_EXE_PREFIXES = ('language_server', 'antigravity', 'agy')

# Patterns handed to pgrep to *nominate* candidates. Nomination is cheap and
# deliberately loose; every candidate is then verified by executable identity
# and by actually owning a listening loopback socket. `-x` matches the kernel
# `comm`, which is capped at 15 characters, so the long legacy binary name has
# to be nominated via `-f`.
_LS_PGREP_PATTERNS = (
    ('-f', 'language_server_linux_x64'),
    ('-f', 'language_server'),
    ('-x', 'agy'),
    ('-x', 'antigravity'),
    ('-x', 'antigravity-ide'),
)

# Kernel socket tables, as a constant so tests can point at fixtures.
_PROC_NET_FILES = ("/proc/net/tcp", "/proc/net/tcp6")

# There is deliberately no fallback port list and no "scan whatever is
# listening" path. Both used to exist, and both were actively harmful: when
# process detection failed, the collector POSTed a quota RPC body at every
# local listening port above 1024 -- unrelated services, and even
# non-loopback addresses on this host's Tailscale interface. An unidentifiable
# language server is reported as unavailable instead.


def _process_exe_name(pid):
    """The executable name behind a pid, or '' if it cannot be determined."""
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except Exception:
        pass
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except Exception:
        return ''


def _is_language_server_exe(name):
    """Whether an executable name is one the quota RPC is served by."""
    if not name:
        return False
    for prefix in _LS_EXE_PREFIXES:
        if name.startswith(prefix):
            return True
        # `comm` is capped at 15 characters, so a longer executable name
        # arrives truncated. Only consider that for names long enough to be
        # unambiguous -- otherwise a short unrelated name like 'ant' would
        # pass as a truncation of 'antigravity'.
        if len(name) >= 10 and prefix.startswith(name):
            return True
    return False


def _own_pid_lineage():
    """This process and its launcher shells/subprocesses that must not be nominated.

    `pgrep -f` matches on the command line, so the poller's own python process
    -- and the shell that launched it, whose command line quotes this module's
    patterns -- can nominate themselves.

    We never add a language server / editor process to the exclusion set: if the
    poller is executed from inside an Antigravity integrated terminal or an
    `agy` session, the editor is an ancestor and is the very process serving
    the quota RPC.
    """
    lineage = set()
    pid = os.getpid()
    lineage.add(pid)
    for _ in range(12):  # bounded: never walk a cycle or a deep tree forever
        try:
            with open(f"/proc/{pid}/stat") as f:
                # field 4 is ppid; the comm field may contain spaces, so read
                # past its closing paren rather than splitting the whole line.
                stat = f.read()
            ppid = int(stat[stat.rindex(')') + 1:].split()[1])
        except Exception:
            break
        if ppid <= 1 or ppid in lineage:
            break
        if _is_language_server_exe(_process_exe_name(ppid)):
            break
        lineage.add(ppid)
        pid = ppid
    return lineage


def _detect_language_server_pids():
    """PIDs of processes that actually serve the quota RPC.

    Candidates are nominated with pgrep and then *verified* against their real
    executable. The previous implementation trusted `pgrep -f` directly, which
    matches any process whose command line merely contains the pattern -- in
    practice the poller's own shell -- and a false positive there sent port
    detection down its indiscriminate fallback path, producing a burst of
    doomed requests to unrelated local services.
    """
    excluded = _own_pid_lineage()
    pids = []
    for flag, pattern in _LS_PGREP_PATTERNS:
        try:
            out = subprocess.check_output(['pgrep', flag, pattern], timeout=2)
        except Exception:
            continue
        for token in out.decode().split():
            if not token.isdigit():
                continue
            pid = int(token)
            if pid in excluded or pid in pids:
                continue
            if _is_language_server_exe(_process_exe_name(pid)):
                pids.append(pid)
    return pids


def _socket_inodes_for_pids(pids):
    """Inodes of every socket held by the given pids."""
    inodes = set()
    for pid in pids:
        fd_dir = f"/proc/{pid}/fd"
        try:
            entries = os.listdir(fd_dir)
        except Exception:
            continue
        for fd in entries:
            try:
                link = os.readlink(os.path.join(fd_dir, fd))
            except Exception:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
    return inodes


def _decode_proc_net_address(hex_addr):
    """Decode a /proc/net/tcp{,6} local address into an ip_address, or None.

    The hex is a sequence of little-endian 32-bit words, so it cannot simply
    be read left to right.
    """
    try:
        if len(hex_addr) == 8:
            return ipaddress.ip_address(
                socket.inet_ntop(socket.AF_INET,
                                 struct.pack('<I', int(hex_addr, 16))))
        if len(hex_addr) == 32:
            raw = b''.join(struct.pack('<I', int(hex_addr[i:i + 8], 16))
                           for i in range(0, 32, 8))
            return ipaddress.ip_address(socket.inet_ntop(socket.AF_INET6, raw))
    except Exception:
        return None
    return None


def _detect_language_server_ports():
    """Loopback ports on which the language server is listening.

    Returns [] when no language server can be identified -- which is the
    normal state whenever Antigravity simply is not running. Callers must
    treat that as "unavailable", not as an error, and must not guess a port:
    the RPC body is POSTed to whatever answers, so a wrong port means sending
    a request to an unrelated service.
    """
    pids = _detect_language_server_pids()
    if not pids:
        return []

    inodes = _socket_inodes_for_pids(pids)
    if not inodes:
        return []

    ports = []
    for net_file in _PROC_NET_FILES:
        try:
            with open(net_file, "r") as f:
                lines = f.readlines()
        except Exception:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            state, inode, local = parts[3], parts[9], parts[1]
            # "0A" is TCP_LISTEN.
            if state != "0A" or inode not in inodes:
                continue
            if ":" not in local:
                continue
            ip_hex, port_hex = local.rsplit(":", 1)
            address = _decode_proc_net_address(ip_hex)
            # Loopback only. The old code parsed the address and then threw it
            # away, so a port bound to a routable interface was treated as a
            # local RPC endpoint.
            if address is None or not address.is_loopback:
                continue
            try:
                port = int(port_hex, 16)
            except ValueError:
                continue
            if port and port not in ports:
                ports.append(port)
    return ports


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


def _short_reason(exc):
    """A compact, non-identifying description of a failed request."""
    reason = getattr(exc, 'reason', None)
    text = str(reason if reason is not None else exc) or type(exc).__name__
    code = getattr(exc, 'code', None)
    if code:
        text = f'HTTP {code}'
    text = ' '.join(str(text).split())
    home = os.path.expanduser('~')
    if home and home != '/':
        text = text.replace(home, '~')
    return text[:80]


def _try_connect_rpc(port, csrf_token=None, timeout=3, errors=None):
    """Try to call the RetrieveUserQuotaSummary RPC on the given port.

    *csrf_token* is optional: the legacy language_server binary required it,
    but newer AGY builds embed the RPC endpoint directly and accept requests
    without a CSRF token.

    *errors*, when given, collects a short reason per failed attempt so the
    caller can report why rather than just that.
    """
    # Try HTTP first, then HTTPS if needed
    for proto in ('http', 'https'):
        url = f'{proto}://127.0.0.1:{port}{QUOTA_RPC_PATH}'
        ctx = None
        if proto == 'https':
            # Verification is disabled only because the language server presents an
            # ephemeral, self-signed loopback cert with no stable identity to check
            # against. This is safe *only* because the target is hardcoded to
            # 127.0.0.1 above — assert that invariant so it can't silently drift.
            assert url.startswith('https://127.0.0.1:'), \
                "refusing to skip TLS verification for a non-loopback target"
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        headers = {
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
        }
        if csrf_token:
            headers['x-codeium-csrf-token'] = csrf_token

        req = urllib.request.Request(
            url, data=b'{}',
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            # Keep the first real reason. Reporting "connection refused" or
            # "403" instead of a generic failure is the difference between a
            # diagnosable log line and the blanket 'fetch failed' that hid
            # this collector's actual behaviour for weeks.
            if errors is not None and len(errors) < 4:
                errors.append(f'{proto}: {_short_reason(e)}')
            continue
    raise Exception(f"Failed to connect to RPC on port {port}")


def _detect_agy_plan(timeout=5):
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def fetch_agy_quota(network_timeout=None):
    """
    Fetch remaining quota from AGY and format it for database storage.

    network_timeout: seconds for each HTTP call, normally Config.network_timeout
    (USAGE_NETWORK_TIMEOUT). None keeps this module's own historical per-call
    defaults (3s for the RPC probe, 5s for plan detection) for callers that
    don't pass config through.

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
    plan_kwargs = {} if network_timeout is None else {'timeout': network_timeout}
    rpc_kwargs = {} if network_timeout is None else {'timeout': network_timeout}

    plan = _detect_agy_plan(**plan_kwargs)
    csrf_token = _detect_csrf_token()  # None when AGY embeds the RPC

    raw_data = None
    ports = _detect_language_server_ports()
    if not ports:
        # No usable endpoint. This is an ordinary, expected state -- Antigravity
        # is a desktop editor, not a service, so it is closed much of the time
        # -- and it is reported as unavailable with its own category rather
        # than as a collection error. `quota_error` (not `error`) keeps the
        # plan, so the dashboard's badge and its last snapshot survive instead
        # of the card disappearing.
        #
        # `ports`, not the pid list, is the gate: a caller (or a test) that
        # supplies a port should reach the RPC regardless. The pid lookup only
        # sharpens the message.
        if _detect_language_server_pids():
            return {
                'plan': plan,
                'quota_error': ('Antigravity is running but is not listening for its '
                                'quota RPC on loopback.'),
                'error_category': 'rpc_port_unavailable',
            }
        return {
            'plan': plan,
            'quota_error': 'Antigravity is not running, so its local quota RPC is unavailable.',
            'error_category': 'not_running',
        }

    errors = []
    for port in ports:
        try:
            raw_data = _try_connect_rpc(port, csrf_token, errors=errors, **rpc_kwargs)
            if raw_data:
                break
        except Exception as e:
            errors.append(_short_reason(e))
            continue

    if not raw_data or 'response' not in raw_data:
        detail = '; '.join(dict.fromkeys(errors)) if errors else 'no response body'
        return {
            'plan': plan,
            'quota_error': (
                f'Antigravity is running but its quota RPC did not answer on '
                f'{len(ports)} loopback port(s): {detail}'
            ),
            'error_category': 'rpc_unavailable',
        }

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
        return {
            'plan': plan,
            'quota_error': f'Failed to parse quota data from Antigravity: {_short_reason(e)}',
            'error_category': 'parse_error',
        }
