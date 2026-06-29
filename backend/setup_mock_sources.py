"""Create mock source files for CI so all verify.py checks pass."""
import base64
import json
import os
import sqlite3
import shutil
import stat
import sys

CI_MOCK_DIR = os.path.join(os.path.dirname(__file__), '.ci_mocks')


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


def setup_mock_opencode():
    """Create a mock `opencode` shell script on PATH."""
    bin_dir = os.path.join(CI_MOCK_DIR, 'bin')
    os.makedirs(bin_dir, exist_ok=True)
    script = bin_dir + '/opencode'
    with open(script, 'w') as f:
        f.write('''#!/usr/bin/env bash
cat <<'EOF'
┌──────────────────────────────────────────────────────────────────────┐
│                           OVERVIEW                                   │
├──────────────────────────────────────────────────────────────────────┤
│ Sessions        20                                                    │
│ Messages        20                                                    │
├──────────────────────────────────────────────────────────────────────┤
│                       COST & TOKENS                                   │
├──────────────────────────────────────────────────────────────────────┤
│ Input           63,000                                                │
│ Output          12,300                                                │
│ Cache Read      17,000                                                │
│ Cache Write     4,000                                                 │
├──────────────────────────────────────────────────────────────────────┤
│                         MODEL USAGE                                   │
├──────────────────────────────────────────────────────────────────────┤
│ opencode/gemini-2.5-pro                                               │
│   Messages         12                                                 │
│   Input Tokens     45,000                                             │
│   Output Tokens    8,200                                              │
│   Cache Read       12,000                                             │
│   Cache Write      3,000                                              │
│   Cost             $0.45                                              │
├──────────────────────────────────────────────────────────────────────┤
│ opencode/claude-sonnet-4.0                                            │
│   Messages         8                                                  │
│   Input Tokens     18,000                                             │
│   Output Tokens    4,100                                              │
│   Cache Read       5,000                                              │
│   Cache Write      1,000                                              │
│   Cost             $0.08                                              │
└──────────────────────────────────────────────────────────────────────┘
EOF
exit 0
''')
    os.chmod(script, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    print(f"  mock opencode script at {script}")
    return bin_dir


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


def setup_mock_codex():
    """Create Codex state DB, logs DB, and auth.json with JWT."""
    codex_dir = os.path.expanduser('~/.codex')
    os.makedirs(codex_dir, exist_ok=True)

    state_db = os.path.join(codex_dir, 'state_5.sqlite')
    conn = sqlite3.connect(state_db)
    conn.execute('CREATE TABLE IF NOT EXISTS threads (id INTEGER, model TEXT, tokens_used INTEGER)')
    conn.execute('INSERT INTO threads (id, model, tokens_used) VALUES (?, ?, ?)', (1, 'gpt-4o', 38000))
    conn.execute('INSERT INTO threads (id, model, tokens_used) VALUES (?, ?, ?)', (2, 'o3-mini', 11000))
    conn.commit()
    conn.close()
    print(f"  Codex state DB at {state_db}")

    logs_db = os.path.join(codex_dir, 'logs_2.sqlite')
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
    padded = jwt_payload
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


def main():
    print("Setting up mock source files for CI...")
    if os.path.exists(CI_MOCK_DIR):
        shutil.rmtree(CI_MOCK_DIR)

    bin_dir = setup_mock_opencode()
    setup_mock_agy()
    setup_mock_codex()

    # Print PATH export for CI
    print(f"\nExport PATH: export PATH={bin_dir}:$PATH")
    print("Done. Mock sources ready.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
