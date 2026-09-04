"""Codex subscription quota collection.

Quota comes from the locally installed Codex CLI's App Server, over a
short-lived stdio JSON-RPC session:

    codex app-server --stdio   ->  initialize  ->  account/rateLimits/read

The protocol is documented by the binary itself; regenerate the reference with

    codex app-server generate-json-schema --out <dir>

which emits `GetAccountRateLimitsResponse`, `RateLimitSnapshot` and
`RateLimitWindow`. That schema is authoritative and version-matched to the
installed CLI, so prefer it over any prose documentation.

Nothing identifying is retained: the access token, the App Server's stderr and
the response's `accountId` / reset-credit ids are never stored, logged or
returned to the caller.
"""

import base64
import json
import os
import queue
import signal
import re
import shutil
import sqlite3
import subprocess
import threading
import time

AUTH_PATH = os.path.expanduser('~/.codex/auth.json')
CODEX_DB = os.path.expanduser('~/.codex/state_5.sqlite')
CODEX_LOGS = os.path.expanduser('~/.codex/logs_2.sqlite')

# Fallback locations probed when `codex` is not on PATH. A systemd unit does
# not normally inherit a user's ~/.local/bin, which is where the official
# installer puts the binary.
_BIN_FALLBACKS = ('~/.local/bin/codex', '/usr/local/bin/codex')

_DEFAULT_TIMEOUT = 10

# How long to let the child wind down politely before killing it.
_TERM_GRACE_SECONDS = 1.5

# A reset timestamp beyond this is milliseconds, not seconds. The protocol
# schema types `resetsAt` as a bare int64 with no documented unit; the values
# observed in practice are Unix seconds, but neighbouring protocol fields
# (`emittedAtMs`) are milliseconds, so the ambiguity is worth guarding.
_MS_THRESHOLD = 10_000_000_000


class CodexQuotaError(Exception):
    """A collection failure with a stable, non-identifying category."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


def _redact(text: str, limit: int = 200) -> str:
    """Strip anything host- or account-identifying out of an error string."""
    if not text:
        return ''
    text = str(text)
    home = os.path.expanduser('~')
    if home and home != '/':
        text = text.replace(home, '~')
    # Absolute paths and anything token-shaped never reach the caller.
    text = re.sub(r'/(?:[\w.\-]+/){2,}[\w.\-]*', '<path>', text)
    text = re.sub(r'\b[A-Za-z0-9_-]{40,}\b', '<redacted>', text)
    text = ' '.join(text.split())
    return text[:limit]


# --- Binary discovery ---------------------------------------------------


def find_codex_bin(configured: str = 'codex') -> str | None:
    """Resolve the Codex executable, or None if it cannot be found.

    An explicitly configured value is honoured as given (USAGE_CODEX_BIN);
    only the default name falls back to probing the usual install locations.
    """
    configured = (configured or 'codex').strip()

    if configured != 'codex':
        if os.path.sep in configured:
            expanded = os.path.expanduser(configured)
            if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
                return expanded
            return None
        return shutil.which(configured)

    found = shutil.which('codex')
    if found:
        return found
    for candidate in _BIN_FALLBACKS:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    return None


# --- App Server JSON-RPC client -----------------------------------------


class _AppServerSession:
    """One short-lived `codex app-server --stdio` conversation.

    A single wall-clock deadline covers process startup, initialization and
    the quota read together, so a server that is slow at every step cannot
    stretch the total wait to a multiple of the configured timeout.
    """

    def __init__(self, codex_bin: str, timeout: float):
        self.codex_bin = codex_bin
        self.deadline = time.time() + timeout
        self.proc = None
        self._queue: queue.Queue = queue.Queue()
        self._next_id = 0

    def __enter__(self):
        try:
            self.proc = subprocess.Popen(
                [self.codex_bin, 'app-server', '--stdio'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # Discarded rather than captured: App Server stderr can carry
                # account detail, and an unread pipe would eventually block
                # the child.
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
                # Own process group, so cleanup can signal the whole tree. A
                # wrapper script that spawns the real binary would otherwise
                # leave the grandchild orphaned, still holding the stdout pipe
                # -- which both leaks the process and wedges the reader thread.
                start_new_session=True,
            )
        except FileNotFoundError:
            raise CodexQuotaError('binary_not_found',
                                  'Codex binary not found') from None
        except OSError as e:
            raise CodexQuotaError('spawn_failed',
                                  f'Could not start Codex App Server: {_redact(e.strerror)}') from None

        # stdout is drained by a thread so the deadline is always enforceable:
        # a bare readline() would block past it if the server went quiet.
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _drain(self):
        try:
            for line in self.proc.stdout:
                self._queue.put(line)
        except Exception:
            pass
        finally:
            self._queue.put(None)

    def _signal_group(self, sig):
        """Signal the child's whole process group.

        Best-effort by design: cleanup must never raise, whatever state the
        child is in. Killing the child alone is not enough when it is a
        wrapper that spawned the real binary -- the grandchild would survive
        holding the stdout pipe.
        """
        try:
            os.killpg(os.getpgid(self.proc.pid), sig)
        except Exception:
            pass

    def close(self):
        """Always reap the child, on every path out."""
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        self._signal_group(signal.SIGTERM)
        try:
            proc.wait(timeout=_TERM_GRACE_SECONDS)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            self._signal_group(signal.SIGKILL)
            try:
                proc.wait(timeout=_TERM_GRACE_SECONDS)
            except Exception:
                pass
        # proc.stdout is deliberately NOT closed here. The reader thread may be
        # blocked inside it, and closing a buffered reader from another thread
        # waits on the lock that thread holds -- a hang, in the exact situation
        # cleanup exists to resolve. The thread is a daemon and the pipe is
        # released when it drains or the interpreter exits.
        self.proc = None

    def _remaining(self) -> float:
        return self.deadline - time.time()

    def _send(self, payload: dict):
        try:
            self.proc.stdin.write(json.dumps(payload) + '\n')
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            raise CodexQuotaError('protocol_error',
                                  'Codex App Server closed the connection') from None

    def _await(self, expected_id: int) -> dict:
        """Read until the response with `expected_id` arrives.

        Server-initiated notifications (no `id`) and responses to other ids
        are interleaved with the reply -- `remoteControl/status/changed`
        reliably arrives before the quota response -- so the next line of
        stdout is never assumed to be the answer.
        """
        while True:
            remaining = self._remaining()
            if remaining <= 0:
                raise CodexQuotaError('timeout', 'Codex App Server timed out')
            try:
                line = self._queue.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                continue
            if line is None:
                raise CodexQuotaError('protocol_error',
                                      'Codex App Server exited before responding')
            line = line.strip()
            if not line:
                continue
            if not line.startswith('{'):
                # Non-protocol chatter on stdout; ignore it rather than fail.
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                raise CodexQuotaError('protocol_error',
                                      'Malformed JSON from Codex App Server') from None
            if not isinstance(msg, dict) or msg.get('id') != expected_id:
                continue
            if 'error' in msg:
                err = msg['error'] or {}
                detail = _redact(err.get('message', '')) if isinstance(err, dict) else ''
                raise CodexQuotaError('protocol_error',
                                      f'Codex App Server error: {detail}' if detail
                                      else 'Codex App Server returned an error')
            result = msg.get('result')
            return result if isinstance(result, dict) else {}

    def request(self, method: str, params=None) -> dict:
        self._next_id += 1
        rid = self._next_id
        payload = {'jsonrpc': '2.0', 'id': rid, 'method': method}
        if params is not None:
            payload['params'] = params
        self._send(payload)
        return self._await(rid)

    def notify(self, method: str, params=None):
        payload = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        self._send(payload)


def fetch_app_server_rate_limits(codex_bin: str, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """Return the raw `account/rateLimits/read` result. Raises CodexQuotaError."""
    with _AppServerSession(codex_bin, timeout) as session:
        session.request('initialize', {
            'clientInfo': {
                'name': 'ai-usage-dashboard',
                'title': 'AI Usage Dashboard',
                'version': '0.1.0',
            },
        })
        session.notify('initialized', {})
        return session.request('account/rateLimits/read')


# --- Protocol normalization ---------------------------------------------


def _coerce_reset_at(value) -> int:
    """Return a Unix-seconds reset timestamp, or 0 when unusable."""
    if value is None:
        return 0
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    if ts > _MS_THRESHOLD:
        ts //= 1000
    return ts


def _window_to_limit(window, bucket, key: str, window_kind: str) -> dict | None:
    """Convert one RateLimitWindow into an internal limit entry.

    A bucket whose numbers are unusable is dropped on its own; it never
    discards a valid sibling window or bucket.
    """
    if not isinstance(window, dict):
        return None
    if 'usedPercent' not in window:
        return None
    try:
        used_pct = float(window['usedPercent'])
    except (TypeError, ValueError):
        return None
    if used_pct != used_pct:  # NaN
        return None

    anomaly = not (0.0 <= used_pct <= 100.0)

    window_minutes = window.get('windowDurationMins')
    try:
        window_minutes = int(window_minutes) if window_minutes is not None else 0
    except (TypeError, ValueError):
        window_minutes = 0
    if window_minutes < 0:
        window_minutes = 0

    reset_at = _coerce_reset_at(window.get('resetsAt'))

    reached_type = bucket.get('rateLimitReachedType')
    return {
        'key': key,
        'bucket_id': bucket.get('limitId') or '',
        'label': bucket.get('limitName') or '',
        'window_kind': window_kind,
        'used_pct': used_pct,
        'window_minutes': window_minutes,
        'reset_at': reset_at,
        'limit_reached': bool(reached_type),
        'reached_type': reached_type or '',
        'spend_control_reached': bool(bucket.get('spendControlReached')),
        'anomalous': anomaly,
    }


def _slug(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', str(value or '').lower()).strip('_')
    return slug or 'bucket'


def normalize_app_server_response(response: dict) -> dict:
    """Map `GetAccountRateLimitsResponse` onto this module's internal format.

    `rateLimits` is documented as a backward-compatible mirror of one entry in
    `rateLimitsByLimitId`, so the two overlap: the same bucket is emitted
    twice by the live protocol. Buckets are therefore keyed by `limitId` and
    de-duplicated, with `rateLimits` used directly only when the multi-bucket
    map is absent or empty.
    """
    if not isinstance(response, dict):
        return {}

    primary_bucket = response.get('rateLimits')
    by_id = response.get('rateLimitsByLimitId')

    ordered = []
    seen = set()

    def _add(bucket):
        if not isinstance(bucket, dict):
            return
        bid = bucket.get('limitId') or ''
        marker = bid or id(bucket)
        if marker in seen:
            return
        seen.add(marker)
        ordered.append(bucket)

    # The mirrored bucket leads, so the account's headline limit keeps the
    # stable 'rate_limit' key regardless of dict ordering upstream.
    _add(primary_bucket)
    if isinstance(by_id, dict):
        for _, bucket in by_id.items():
            _add(bucket)

    limits = []
    for index, bucket in enumerate(ordered):
        if index == 0:
            base = 'rate_limit'
        else:
            base = f'rate_limit_{_slug(bucket.get("limitId"))}'
        entry = _window_to_limit(bucket.get('primary'), bucket, base, 'primary')
        if entry:
            limits.append(entry)
        secondary = _window_to_limit(bucket.get('secondary'), bucket,
                                     f'{base}_secondary', 'secondary')
        if secondary:
            limits.append(secondary)

    plan_type = ''
    for bucket in ordered:
        if isinstance(bucket, dict) and bucket.get('planType'):
            plan_type = str(bucket['planType'])
            break

    raw: dict = {'limits': limits}
    if plan_type:
        raw['plan_type'] = plan_type

    # Flat primary keys preserve the historical contract that the stored
    # snapshots, the normalizers and the log fallback all already speak.
    if limits:
        head = limits[0]
        now = time.time()
        raw.update({
            'primary_used_pct': head['used_pct'],
            'window_minutes': head['window_minutes'],
            'reset_at': head['reset_at'],
            'resets_in_seconds': max(0, int(head['reset_at'] - now)) if head['reset_at'] > now else 0,
            'limit_reached': head['limit_reached'],
            'allowed': not head['limit_reached'],
        })
    return raw


# --- Plan (display-only) -------------------------------------------------


def _get_plan_from_jwt():
    """Extract the plan type from the JWT in auth.json.

    The signature is intentionally not verified: this claim is read for
    display only (the plan label on the dashboard). Never use it for
    authorization or any other trust decision. Only the plan type is
    returned -- the account and org ids are deliberately dropped.
    """
    if not os.path.exists(AUTH_PATH):
        return None
    try:
        with open(AUTH_PATH) as f:
            auth = json.load(f)
        tokens = auth.get('tokens', {})
        for token_key in ('access_token', 'id_token'):
            token = tokens.get(token_key, '')
            if not token:
                continue
            parts = token.split('.')
            if len(parts) != 3:
                continue
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            try:
                payload = json.loads(base64.urlsafe_b64decode(padded))
            except Exception:
                continue
            auth_data = payload.get('https://api.openai.com/auth', {})
            if auth_data.get('chatgpt_plan_type'):
                return {'plan_type': auth_data['chatgpt_plan_type']}
        return {'plan_type': 'unknown'}
    except Exception:
        return {'plan_type': 'unknown'}


# --- Deprecated log fallback --------------------------------------------


def _parse_logs_for_limits():
    """DEPRECATED: scrape a quota payload out of the Codex CLI's log database.

    Codex CLI 0.153.1 does not write these payloads -- every `rate_limits`
    match in `logs_2.sqlite` is otel tracing text -- so on a current install
    this always returns None. It is retained only as a compatibility path for
    older releases that did embed the JSON, and is consulted after the App
    Server, never before.
    """
    if not os.path.exists(CODEX_LOGS):
        return None
    conn = None
    try:
        # mode=ro: these DBs are WAL-mode and need read-write access to their
        # -shm sidecar to open at all; the systemd unit grants that via
        # ReadWritePaths on ~/.codex (see install/usage-dashboard.service).
        conn = sqlite3.connect(f'file:{CODEX_LOGS}?mode=ro', uri=True)
        cursor = conn.execute(
            "SELECT feedback_log_body FROM logs WHERE feedback_log_body LIKE '%rate_limits%' OR feedback_log_body LIKE '%rateLimits%' ORDER BY id DESC LIMIT 50"
        )
        rows = cursor.fetchall()
        if not rows:
            return None

        data = None
        for row in rows:
            body = row[0]
            if not body:
                continue
            idx = body.find('"type":"codex.rate_limits"')
            if idx < 0:
                idx = body.find('"rate_limits"')
            if idx < 0:
                continue
            start = body.rfind('{', 0, idx)
            if start < 0:
                continue
            try:
                parsed, _ = json.JSONDecoder().raw_decode(body, start)
                if parsed and isinstance(parsed, dict) and ('rate_limits' in parsed or 'rateLimits' in parsed):
                    data = parsed
                    break
            except Exception:
                continue

        if not data:
            return None
        limits = data.get('rate_limits', data.get('rateLimits', {})) or {}
        primary = limits.get('primary', {}) or {}
        # Historical payloads used snake_case; newer ones camelCase. Accept both.
        reset_at = _coerce_reset_at(primary.get('reset_at', primary.get('resetsAt')))
        now = time.time()

        if reset_at > 0 and reset_at < now:
            # The rate limit window has expired and reset
            used_pct = 0.0
            resets_in = 0
            limit_reached = False
            allowed = True
        else:
            used_pct = float(primary.get('used_percent', primary.get('usedPercent', 0)) or 0)
            resets_in = max(0, int(reset_at - now))
            limit_reached = limits.get('limit_reached', False)
            allowed = limits.get('allowed', True)

        window_minutes = primary.get('window_minutes', primary.get('windowDurationMins', 0))
        try:
            window_minutes = int(window_minutes or 0)
        except (TypeError, ValueError):
            window_minutes = 0

        return {
            'plan_type': data.get('plan_type', data.get('planType', 'unknown')),
            'primary_used_pct': used_pct,
            'window_minutes': window_minutes,
            'resets_in_seconds': resets_in,
            'reset_at': reset_at,
            'limit_reached': limit_reached,
            'allowed': allowed,
            'limits': [{
                'key': 'rate_limit',
                'bucket_id': '',
                'label': '',
                'window_kind': 'primary',
                'used_pct': used_pct,
                'window_minutes': window_minutes,
                'reset_at': reset_at,
                'limit_reached': bool(limit_reached),
                'reached_type': '',
                'spend_control_reached': False,
                'anomalous': not (0.0 <= used_pct <= 100.0),
            }],
        }
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# --- Local telemetry -----------------------------------------------------


def _get_token_stats():
    """Local thread-token totals.

    This is usage telemetry, not a quota: it says how many tokens local
    threads consumed, and nothing about the subscription allowance. It is
    never used to derive or estimate a limit.
    """
    if not os.path.exists(CODEX_DB):
        return None
    try:
        # mode=ro: see _parse_logs_for_limits above.
        conn = sqlite3.connect(f'file:{CODEX_DB}?mode=ro', uri=True)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT model, tokens_used FROM threads")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()
    except Exception:
        return None
    if not rows:
        return None
    model_sessions = {}
    total_tokens = 0
    for model, tokens in rows:
        tokens = tokens or 0
        model_sessions[model] = model_sessions.get(model, 0) + 1
        total_tokens += tokens
    return {
        'total_sessions': len(rows),
        'total_tokens': total_tokens,
        'model_sessions': model_sessions,
    }


# --- Public entry point --------------------------------------------------


def fetch_codex_quota(codex_bin: str = 'codex', timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """Collect Codex plan and subscription quota.

    Returns the internal raw format consumed by the Codex normalizers. On
    failure the result still carries whatever is locally known (the plan, and
    thread-token telemetry), plus a safe `error`/`error_category` pair -- a
    quota read that fails must not blank out the plan badge.
    """
    plan_info = _get_plan_from_jwt()
    tokens = _get_token_stats()

    result: dict = {}
    error = None
    error_category = None

    resolved_bin = find_codex_bin(codex_bin)
    if not resolved_bin:
        error_category = 'binary_not_found'
        error = ('Codex binary not found. Set USAGE_CODEX_BIN to its full path '
                 '(the installer usually puts it in ~/.local/bin).')
    else:
        try:
            response = fetch_app_server_rate_limits(resolved_bin, timeout)
            result.update(normalize_app_server_response(response))
        except CodexQuotaError as e:
            error_category = e.category
            error = e.message
        except Exception as e:  # never let a collector crash the poll cycle
            error_category = 'unavailable'
            error = f'Codex quota unavailable: {_redact(type(e).__name__)}'

    if 'primary_used_pct' not in result:
        # Compatibility path for older Codex releases only; a current install
        # has no such payload and this is a no-op.
        legacy = _parse_logs_for_limits()
        if legacy:
            result.update(legacy)
            error = None
            error_category = None

    if plan_info and not result.get('plan_type'):
        result['plan_type'] = plan_info['plan_type']

    plan_type = result.get('plan_type')
    if plan_type:
        plan_label = str(plan_type).capitalize()
        result['plan'] = f'Codex ({plan_label})'

    if tokens:
        result['tokens'] = tokens

    if error:
        result['error_category'] = error_category
        # `error` alone means "nothing usable"; when a plan survives, the
        # failure is reported without discarding what is known.
        if result.get('plan') or result.get('tokens'):
            result['quota_error'] = error
        else:
            result['error'] = error

    if not result:
        return {'error': 'No Codex data found.', 'error_category': 'unavailable'}

    return result


# --- Shared normalizer ---------------------------------------------------

_WINDOW_LABELS = (
    (43200, 'Monthly'),
    (10080, 'Weekly'),
    (1440, 'Daily'),
)


def window_label(window_minutes: int) -> str:
    """Human name for a quota window, e.g. 'Monthly' or '5h window'."""
    try:
        wm = int(window_minutes or 0)
    except (TypeError, ValueError):
        return ''
    if wm <= 0:
        return ''
    for threshold, label in _WINDOW_LABELS:
        if wm >= threshold:
            return label
    if wm >= 60:
        return f'{round(wm / 60)}h window'
    return f'{wm}m window'


def _limit_entry(entry: dict) -> dict:
    """One internal limit -> one API/DB limit row."""
    used = entry.get('used_pct', 0.0)
    # The stored `used` stays as reported so a protocol anomaly is visible in
    # the data; only the displayed remaining percentage is clamped.
    remaining = max(0.0, min(100.0, 100.0 - used))
    reset_at = entry.get('reset_at', 0) or 0
    now = time.time()
    resets_in = max(0, int(reset_at - now)) if reset_at > now else 0
    label = entry.get('label') or window_label(entry.get('window_minutes', 0))
    if entry.get('window_kind') == 'secondary' and label:
        label = f'Secondary ({label})'
    row = {
        'used': used,
        'total': 100.0,
        'remaining_pct': remaining,
        'refreshes_in_seconds': resets_in,
        'reset_at': reset_at,
        'window_minutes': entry.get('window_minutes', 0),
        'limit_label': label,
    }
    if entry.get('limit_reached'):
        row['limit_reached'] = True
    if entry.get('anomalous'):
        row['anomalous'] = True
    return row


def normalize_quota(raw) -> dict | None:
    """Canonical Codex normalizer, shared by the YAML provider and the
    hard-coded registry so the two cannot drift apart.

    Emits an `openai` group whose first bucket keeps the stable `rate_limit`
    key; additional windows and buckets get their own keys alongside it and
    never overwrite one another.
    """
    if not raw or not isinstance(raw, dict):
        return None
    # A hard error carries nothing usable; a `quota_error` still has a plan.
    if 'error' in raw:
        return None

    result: dict = {}
    plan = raw.get('plan_type') or raw.get('plan', 'free')
    result['_plan'] = plan

    group: dict = {}
    limits = raw.get('limits')
    if isinstance(limits, list) and limits:
        for entry in limits:
            if not isinstance(entry, dict):
                continue
            key = entry.get('key') or 'rate_limit'
            if key in group:
                continue
            group[key] = _limit_entry(entry)
    elif 'primary_used_pct' in raw:
        # Legacy raw/stored shape with only flat primary fields.
        group['rate_limit'] = _limit_entry({
            'used_pct': raw['primary_used_pct'],
            'window_minutes': raw.get('window_minutes', 0),
            'reset_at': raw.get('reset_at', 0),
            'window_kind': 'primary',
            'limit_reached': raw.get('limit_reached', False),
        })
        if not group['rate_limit']['refreshes_in_seconds']:
            group['rate_limit']['refreshes_in_seconds'] = raw.get('resets_in_seconds', 0)

    if group:
        result['openai'] = group
    return result
