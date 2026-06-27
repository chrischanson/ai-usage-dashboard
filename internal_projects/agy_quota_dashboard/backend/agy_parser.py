"""
Parser for Antigravity (agy) IDE usage data.
Reads all conversation SQLite databases in the agy CLI directory and
extracts per-model token usage from gen_metadata protobuf blobs.

No network calls, no LLM quota consumed.
"""
import sqlite3
import glob
import os

AGY_CONV_DIR = os.path.expanduser('~/.gemini/antigravity-cli/conversations')
# IDE conversations are also tracked (they share the same brain)
AGY_IDE_CONV_DIR = os.path.expanduser('~/.gemini/antigravity-ide/conversations')


def _read_varint(data: bytes, pos: int):
    """Decode a protobuf varint at position pos. Returns (value, new_pos)."""
    result, shift = 0, 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _scan_fields(data: bytes, depth: int = 0, prefix: str = '') -> dict:
    """
    Recursively parse protobuf blob into a flat dict of field paths → [values].
    Stops at depth 3 to avoid runaway recursion on large nested messages.
    """
    pos, results = 0, {}
    while pos < len(data):
        try:
            tag, pos = _read_varint(data, pos)
            field = tag >> 3
            wtype = tag & 0x7
            if field == 0 and wtype == 0:
                break
            key = f'{prefix}{field}'
            if wtype == 0:   # varint
                val, pos = _read_varint(data, pos)
                results.setdefault(key, []).append(val)
            elif wtype == 2: # length-delimited (string or nested message)
                length, pos = _read_varint(data, pos)
                payload = data[pos:pos+length]
                pos += length
                try:
                    text = payload.decode('utf-8')
                    results.setdefault(key, []).append(text)
                except Exception:
                    if depth < 3:
                        sub = _scan_fields(payload, depth + 1, prefix=f'{key}.')
                        for k, v in sub.items():
                            results.setdefault(k, []).extend(v)
            elif wtype == 1: # 64-bit — skip
                pos += 8
            elif wtype == 5: # 32-bit — skip
                pos += 4
            else:
                break
        except Exception:
            break
    return results


# Model name keywords used to identify model strings in the blobs
_MODEL_KEYWORDS = ['gemini', 'claude', 'flash', 'pro', 'sonnet', 'opus',
                   'gpt', 'ultra', 'haiku', 'mistral', 'llama']


def _extract_model_name(fields: dict) -> str | None:
    """Find the best model name string from parsed protobuf fields."""
    candidates = []
    for vals in fields.values():
        for v in vals:
            if not isinstance(v, str):
                continue
            vl = v.lower()
            if any(k in vl for k in _MODEL_KEYWORDS) and 3 < len(v) < 60 and '\n' not in v:
                candidates.append(v)
    # Prefer shorter, more specific strings
    if candidates:
        return sorted(candidates, key=len)[0]
    return None


def _extract_conv_usage(db_path: str) -> dict | None:
    """
    Parse gen_metadata rows from a single conversation DB.

    Returns dict with:
      input_tokens  — max of field 1.4.2 (cumulative input per conversation)
      output_tokens — max of field 1.4.3 (cumulative output per conversation)
      cache_read    — max of field 1.4.5 (cumulative cache reads)
      model         — model name string (or None)
    """
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        rows = conn.execute('SELECT data FROM gen_metadata ORDER BY idx').fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    max_input = max_output = max_cache = 0
    model_name = None

    for (data,) in rows:
        if not data:
            continue
        f = _scan_fields(data)

        # Field 1.4.2 = cumulative input tokens (increases step-by-step)
        vals = f.get('1.4.2', [])
        if vals:
            max_input = max(max_input, max(vals))

        # Field 1.4.3 = cumulative output tokens
        vals = f.get('1.4.3', [])
        if vals:
            max_output = max(max_output, max(vals))

        # Field 1.4.5 = cumulative cache read tokens
        vals = f.get('1.4.5', [])
        if vals:
            max_cache = max(max_cache, max(vals))

        if not model_name:
            model_name = _extract_model_name(f)

    if max_input == 0 and max_output == 0:
        return None

    return {
        'input_tokens': max_input,
        'output_tokens': max_output,
        'cache_read': max_cache,
        'model': model_name or 'unknown',
    }


def fetch_agy_usage() -> tuple[dict, dict, list]:
    """
    Scan all Antigravity conversation DBs and return aggregated usage.

    Returns: (overview, cost_tokens, models) matching the same format as
    parse_report_content() in parser.py so the rest of the system is uniform.
    """
    db_dirs = [d for d in [AGY_CONV_DIR, AGY_IDE_CONV_DIR] if os.path.isdir(d)]
    db_files = []
    for d in db_dirs:
        db_files.extend(glob.glob(os.path.join(d, '*.db')))

    if not db_files:
        return {}, {}, []

    model_totals: dict[str, dict] = {}
    sessions = 0

    for db_path in db_files:
        usage = _extract_conv_usage(db_path)
        if not usage:
            continue
        sessions += 1
        model = usage['model']
        if model not in model_totals:
            model_totals[model] = {
                'input_tokens': 0,
                'output_tokens': 0,
                'cache_read': 0,
                'messages': 0,
                'cost': 0.0,
            }
        model_totals[model]['input_tokens'] += usage['input_tokens']
        model_totals[model]['output_tokens'] += usage['output_tokens']
        model_totals[model]['cache_read'] += usage['cache_read']
        model_totals[model]['messages'] += 1

    if not model_totals:
        return {}, {}, []

    total_input = sum(v['input_tokens'] for v in model_totals.values())
    total_output = sum(v['output_tokens'] for v in model_totals.values())
    total_cache = sum(v['cache_read'] for v in model_totals.values())

    overview = {
        'Sessions': sessions,
        'Messages': sum(v['messages'] for v in model_totals.values()),
    }
    cost_tokens = {
        'Total Cost': 0.0,
        'Avg Cost/Day': 0.0,
        'Input': total_input,
        'Output': total_output,
        'Cache Read': total_cache,
        'Cache Write': 0,
    }
    models = [
        {
            'name': model,
            'Messages': data['messages'],
            'Input Tokens': data['input_tokens'],
            'Output Tokens': data['output_tokens'],
            'Cache Read': data['cache_read'],
            'Cache Write': 0,
            'Cost': 0.0,
        }
        for model, data in sorted(model_totals.items(),
                                  key=lambda x: -x[1]['input_tokens'])
    ]

    return overview, cost_tokens, models
