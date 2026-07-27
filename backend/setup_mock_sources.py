"""Create mock source files for CI so all verify.py checks pass."""
import base64
import json
import os
import sqlite3
import shutil
import sys


def encode_varint(n):
    buf = bytearray()
    while n > 0x7F:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    buf.append(n)
    return bytes(buf)


def encode_tag(field, wire_type):
    return encode_varint((field << 3) | wire_type)


def encode_len(field, payload):
    return encode_tag(field, 2) + encode_varint(len(payload)) + payload


def encode_varint_field(field, value):
    return encode_tag(field, 0) + encode_varint(value)


def build_agy_protobuf(input_tokens, output_tokens, cache_read, model_name):
    inner = (
        encode_varint_field(2, input_tokens) +
        encode_varint_field(3, output_tokens) +
        encode_varint_field(5, cache_read)
    )
    nested = encode_len(4, inner)
    outer = (
        encode_len(1, nested) +
        encode_len(5, model_name.encode('utf-8'))
    )
    return outer


def setup_mock_agy():
    """Create AGY conversation DBs with protobuf data."""
    conv_dir = os.path.expanduser('~/.gemini/antigravity-cli/conversations')
    ide_dir = os.path.expanduser('~/.gemini/antigravity-ide/conversations')
    os.makedirs(conv_dir, exist_ok=True)
    os.makedirs(ide_dir, exist_ok=True)
    for _dir in (conv_dir, ide_dir):
        db_path = os.path.join(_dir, 'conv_test.db')
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE IF NOT EXISTS gen_metadata (idx INTEGER, data BLOB)')
        blob = build_agy_protobuf(input_tokens=45000, output_tokens=8200, cache_read=12000, model_name='gemini-2.5-pro')
        conn.execute('INSERT INTO gen_metadata (idx, data) VALUES (?, ?)', (0, blob))
        conn.commit()
        conn.close()
        print(f"  AGY conv DB at {db_path}")


def setup_mock_agy_quota():
    """Seed an AGY quota snapshot directly in the app DB.

    fetch_agy_quota() needs a live local language-server RPC (CSRF token
    from a running process's cmdline, etc.) that doesn't exist in CI, so
    the live path always fails there. Seeding quota_snapshots directly
    covers the same ground the poller would if that RPC existed —
    api.py's fallback keeps DB-sourced groups when the live fetch errors.
    """
    import time
    import db as dbmod

    conn = dbmod.connect(dbmod.DB_PATH)
    dbmod.init_schema(conn)
    cycle_ts = int(time.time())
    dbmod.record_quota(conn, 'agy', cycle_ts, {
        # The plan badge comes from the same live RPC that can't run in CI, so
        # seed it here too. Without it /api/quota/latest returns agy with no
        # `_plan` and verify.py's plan-badge check fails.
        '_plan': 'Gemini Code Assist',
        'gemini_models': {
            'weekly_limit': {'used': 20.0, 'total': 100.0, 'remaining_pct': 80.0, 'refreshes_in': 500000},
            'five_hour_limit': {'used': 5.0, 'total': 100.0, 'remaining_pct': 95.0, 'refreshes_in': 15000},
        },
        'claude_gpt_models': {
            'weekly_limit': {'used': 50.0, 'total': 100.0, 'remaining_pct': 50.0, 'refreshes_in': 100000},
            'five_hour_limit': {'used': 0.0, 'total': 100.0, 'remaining_pct': 100.0, 'refreshes_in': 18000},
        },
    })
    conn.close()
    print(f"  AGY quota snapshot seeded in {dbmod.DB_PATH}")


def setup_mock_codex():
    """Create Codex state DB, logs DB, and auth.json with JWT."""
    codex_dir = os.path.expanduser('~/.codex')
    os.makedirs(codex_dir, exist_ok=True)

    state_db = os.path.join(codex_dir, 'state_5.sqlite')
    if os.path.exists(state_db):
        try:
            os.remove(state_db)
        except OSError:
            pass
    conn = sqlite3.connect(state_db)
    conn.execute('CREATE TABLE IF NOT EXISTS threads (id INTEGER, model TEXT, tokens_used INTEGER)')
    conn.execute('INSERT INTO threads (id, model, tokens_used) VALUES (?, ?, ?)', (1, 'gpt-4o', 38000))
    conn.execute('INSERT INTO threads (id, model, tokens_used) VALUES (?, ?, ?)', (2, 'o3-mini', 11000))
    conn.commit()
    conn.close()
    print(f"  Codex state DB at {state_db}")

    logs_db = os.path.join(codex_dir, 'logs_2.sqlite')
    if os.path.exists(logs_db):
        try:
            os.remove(logs_db)
        except OSError:
            pass
    conn = sqlite3.connect(logs_db)
    conn.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER, feedback_log_body TEXT)')
    rate_limit_event = json.dumps({
        "type": "codex.rate_limits",
        "plan_type": "chatgptplusplan",
        "rate_limits": {
            "primary": {
                "used_percent": 42.5,
                "window_minutes": 60,
                "reset_after_seconds": 1800,
                "reset_at": int(__import__('time').time()) + 1800,
            },
            "limit_reached": False,
            "allowed": True,
        }
    })
    conn.execute('INSERT INTO logs (id, feedback_log_body) VALUES (?, ?)', (1, rate_limit_event))
    conn.commit()
    conn.close()
    print(f"  Codex logs DB at {logs_db}")

    jwt_payload = {
        "https://api.openai.com/auth": {
            "chatgpt_plan_type": "chatgptplusplan",
            "chatgpt_account_id": "ci_test_account",
            "organizations": [{"id": "org-ci-test"}],
        }
    }
    encoded = base64.urlsafe_b64encode(json.dumps(jwt_payload).encode()).rstrip(b'=').decode()
    jwt = f"header.{encoded}.signature"
    auth = {
        "tokens": {
            "access_token": jwt,
            "id_token": jwt,
        }
    }
    auth_path = os.path.join(codex_dir, 'auth.json')
    with open(auth_path, 'w') as f:
        json.dump(auth, f)
    print(f"  Codex auth.json at {auth_path}")


_FAKE_OPENCODE_OUTPUT = """\
┌──────────────────────────────────────────────────┐
│                       OVERVIEW                         │
├──────────────────────────────────────────────────┤
│Sessions                                             12 │
│Messages                                            240 │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│                    COST & TOKENS                       │
├──────────────────────────────────────────────────┤
│Input                                              1.0K │
│Output                                               500 │
│Cache Read                                           2.0K │
│Cache Write                                          100 │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│                      MODEL USAGE                       │
├──────────────────────────────────────────────────┤
│ opencode/ci-test-model                                 │
│  Messages                                           240 │
│  Input Tokens                                       1.0K │
│  Output Tokens                                        500 │
│  Cache Read                                         2.0K │
│  Cache Write                                          100 │
│  Cost                                             $0.0100 │
└──────────────────────────────────────────────────┘
"""


def setup_mock_opencode(bin_dir):
    """Write a fake `opencode` executable on PATH so OpenCodeParser has
    something to shell out to in CI (there's no real opencode CLI there)."""
    os.makedirs(bin_dir, exist_ok=True)
    fake_bin = os.path.join(bin_dir, 'opencode')
    with open(fake_bin, 'w') as f:
        f.write("#!/bin/sh\ncat <<'FAKE_OPENCODE_EOF'\n")
        f.write(_FAKE_OPENCODE_OUTPUT)
        f.write("FAKE_OPENCODE_EOF\n")
    os.chmod(fake_bin, 0o755)
    print(f"  Fake opencode binary at {fake_bin}")

    github_path_file = os.environ.get('GITHUB_PATH')
    if github_path_file:
        with open(github_path_file, 'a') as f:
            f.write(bin_dir + '\n')
        print(f"  Added {bin_dir} to $GITHUB_PATH for later steps")
    else:
        print(f"  Not running under GitHub Actions — add {bin_dir} to PATH yourself if testing locally")


def _refuse_outside_ci():
    """Refuse to run anywhere that isn't a disposable CI runner.

    This script is destructive against $HOME. It deletes and recreates
    ~/.codex/state_5.sqlite, ~/.codex/logs_2.sqlite and ~/.codex/auth.json
    (destroying real OpenAI credentials), and drops fake conversation DBs into
    ~/.gemini/*/conversations/ where the AGY parser will count them as real
    usage. None of it is backed up, and none of it is recoverable.

    On 2026-07-26 that happened on a developer machine: real Codex auth and
    logs were destroyed, and a poll ingested 90,000 fabricated AGY tokens into
    the live database before the mocks were removed. The script did print
    "Not running under GitHub Actions" — but only after it had already
    overwritten everything, which is no guard at all.

    So: bail out first, and make the override explicit and awkward to type.
    """
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        return
    if os.environ.get('USAGE_ALLOW_DESTRUCTIVE_HOME_MOCKS') == 'yes-i-am-in-a-sandbox':
        print("  ! override set — writing mocks into HOME=%s" % os.path.expanduser('~'))
        return

    sys.stderr.write(
        "\nREFUSING TO RUN: this script overwrites real files in your home directory.\n"
        f"  HOME is currently {os.path.expanduser('~')}\n\n"
        "  It will DELETE and replace:\n"
        "    ~/.codex/auth.json         (your real OpenAI credentials)\n"
        "    ~/.codex/state_5.sqlite\n"
        "    ~/.codex/logs_2.sqlite\n"
        "  and add fake conversation DBs under:\n"
        "    ~/.gemini/antigravity-{cli,ide}/conversations/conv_test.db\n"
        "  which the AGY parser will then count as real usage.\n\n"
        "  It is meant for a disposable GitHub Actions runner only.\n\n"
        "  To run it locally, isolate HOME first — e.g.\n"
        "    bwrap --dev-bind / / --bind $(mktemp -d) \"$HOME\" \\\n"
        "      env USAGE_ALLOW_DESTRUCTIVE_HOME_MOCKS=yes-i-am-in-a-sandbox \\\n"
        "      python3 backend/setup_mock_sources.py\n\n"
    )
    return 2


def main():
    refused = _refuse_outside_ci()
    if refused:
        return refused

    print("Setting up mock source files for CI...")
    if os.path.exists(os.path.join(os.path.dirname(__file__), '.ci_mocks')):
        shutil.rmtree(os.path.join(os.path.dirname(__file__), '.ci_mocks'))

    setup_mock_agy()
    setup_mock_agy_quota()
    setup_mock_codex()
    setup_mock_opencode(os.path.join(os.path.dirname(__file__), '.ci_mocks', 'bin'))
    print("Done. Mock sources ready.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
