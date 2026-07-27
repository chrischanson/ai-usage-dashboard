"""
Parser for Antigravity (agy) IDE usage data.
Reads all conversation SQLite databases in the agy CLI directory and
extracts per-model token usage from gen_metadata protobuf blobs.
"""
import sqlite3
import glob
import os
import unicodedata

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable

AGY_CONV_DIR = os.path.expanduser('~/.gemini/antigravity-cli/conversations')
AGY_IDE_CONV_DIR = os.path.expanduser('~/.gemini/antigravity-ide/conversations')

_MODEL_KEYWORDS = ['gemini', 'claude', 'flash', 'pro', 'sonnet', 'opus',
                   'gpt', 'ultra', 'haiku', 'mistral', 'llama']

# source_registry builds a brand-new AgyParser every poll cycle (see
# _make_agy_parser), so this cache has to live at module scope to survive
# between cycles. Keyed by (conv_dir, ide_conv_dir) so tests pointed at
# temp dirs never share entries with each other or with the real dirs,
# then by db path -> (fingerprint, usage-dict-or-None).
_DB_CACHE: dict = {}


def _sidecar_fingerprint(path: str):
    # Returns None when the sidecar doesn't exist, which is itself part of
    # the fingerprint: a WAL file appearing/disappearing must invalidate
    # the cache even though the main .db file's (mtime, size) is unchanged.
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _db_fingerprint(db_path: str):
    """(mtime, size) of the main file plus its -wal/-shm sidecars.

    SQLite in WAL mode appends new rows to the -wal file without touching
    the main file's mtime/size, so fingerprinting the main file alone would
    make freshly-written conversations look unchanged forever.
    """
    try:
        st = os.stat(db_path)
    except OSError:
        return None
    return (
        (st.st_mtime, st.st_size),
        _sidecar_fingerprint(db_path + '-wal'),
        _sidecar_fingerprint(db_path + '-shm'),
    )


def normalize_model_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return 'Claude 3.5 Sonnet'
    s = name.strip()
    sl = s.lower()

    if sl.startswith(('used_', 'use_', 'enable-', 'disable-')) or sl in ('used_claude', 'used_non_gemini_model', 'unknown'):
        if '3.7' in sl or '3_7' in sl:
            return 'Claude 3.7 Sonnet'
        if 'opus' in sl:
            return 'Claude 3 Opus'
        if 'haiku' in sl:
            return 'Claude 3 Haiku'
        if 'gemini' in sl:
            if 'pro' in sl:
                return 'Gemini 1.5 Pro'
            return 'Gemini 2.5 Flash'
        return 'Claude 3.5 Sonnet'

    return s


class AgyParser(Parser):
    def __init__(self, conv_dir: str = AGY_CONV_DIR, ide_conv_dir: str = AGY_IDE_CONV_DIR, db_path: str = None, state: dict = None):
        self.conv_dir = conv_dir
        self.ide_conv_dir = ide_conv_dir
        self.db_path = db_path
        self.state = state

    @staticmethod
    def _read_varint(data: bytes, pos: int):
        result, shift = 0, 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return result, pos

    @staticmethod
    def _scan_fields(data: bytes, depth: int = 0, prefix: str = '') -> dict:
        pos, results = 0, {}
        while pos < len(data):
            try:
                tag, pos = AgyParser._read_varint(data, pos)
                field = tag >> 3
                wtype = tag & 0x7
                if field == 0 and wtype == 0:
                    break
                key = f'{prefix}{field}'
                if wtype == 0:
                    val, pos = AgyParser._read_varint(data, pos)
                    results.setdefault(key, []).append(val)
                elif wtype == 2:
                    length, pos = AgyParser._read_varint(data, pos)
                    payload = data[pos:pos + length]
                    pos += length
                    is_text = False
                    try:
                        text = payload.decode('utf-8')
                        # Check if it looks like a valid text string (no control characters except tab, newline, carriage return)
                        if not any(unicodedata.category(c).startswith('C') and c not in '\t\n\r' for c in text):
                            results.setdefault(key, []).append(text)
                            is_text = True
                    except Exception:
                        pass

                    if not is_text and depth < 3:
                        sub = AgyParser._scan_fields(payload, depth + 1, prefix=f'{key}.')
                        for k, v in sub.items():
                            results.setdefault(k, []).extend(v)
                elif wtype == 1:
                    pos += 8
                elif wtype == 5:
                    pos += 4
                else:
                    break
            except Exception:
                break
        return results

    @staticmethod
    def _extract_model_name(fields: dict) -> str | None:
        # Preferred protobuf fields for model name (1.21: display name, 1.19/3.28: raw model id)
        for field_key in ('1.21', '1.19', '3.28'):
            for v in fields.get(field_key, []):
                if isinstance(v, str) and any(k in v.lower() for k in _MODEL_KEYWORDS) and '\n' not in v:
                    vl = v.lower()
                    if not (vl.startswith(('used_', 'use_', 'enable-', 'disable-')) or 'used_claude' in vl or 'used_non_gemini' in vl):
                        return normalize_model_name(v)

        candidates = []
        for vals in fields.values():
            for v in vals:
                if not isinstance(v, str):
                    continue
                vl = v.lower()
                if any(k in vl for k in _MODEL_KEYWORDS) and 3 <= len(v) < 60 and '\n' not in v:
                    candidates.append(v)
        if candidates:
            clean_candidates = [c for c in candidates if not (c.lower().startswith(('used_', 'use_', 'enable-', 'disable-')) or 'used_claude' in c.lower() or 'used_non_gemini' in c.lower())]
            best = sorted(clean_candidates or candidates, key=len)[0]
            return normalize_model_name(best)

        return None
    @staticmethod
    def _extract_conv_usage(db_path: str) -> dict | None:
        """Read token counts and model name from one AGY conversation .db."""
        rows = None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                rows = conn.execute("SELECT data FROM gen_metadata ORDER BY idx").fetchall()
            except Exception:
                row = conn.execute("SELECT f FROM key_value WHERE k='conversation.state'").fetchone()
                if row and row[0]:
                    rows = [(row[0],)]
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
            f = AgyParser._scan_fields(data)

            vals = f.get('1.4.2', [])
            if vals:
                max_input = max(max_input, max(vals))

            vals = f.get('1.4.3', [])
            if vals:
                max_output = max(max_output, max(vals))

            vals = f.get('1.4.5', [])
            if vals:
                max_cache = max(max_cache, max(vals))

            extracted = AgyParser._extract_model_name(f)
            if extracted:
                model_name = extracted

        if not model_name:
            try:
                with open(db_path, 'rb') as f:
                    content = f.read()
                    f_fields = AgyParser._scan_fields(content)
                    model_name = AgyParser._extract_model_name(f_fields)
            except Exception:
                pass

        if max_input == 0 and max_output == 0:
            return None

        return {
            'input_tokens': max_input,
            'output_tokens': max_output,
            'cache_read': max_cache,
            'model': model_name or 'unknown',
        }

    def parse(self, state: dict = None) -> ParserResult:
        db_dirs = [d for d in [self.conv_dir, self.ide_conv_dir] if os.path.isdir(d)]
        db_files = []
        for d in db_dirs:
            db_files.extend(glob.glob(os.path.join(d, '*.db')))

        if not db_files:
            raise SourceUnavailable("No AGY conversation databases found")

        cache_key = (self.conv_dir, self.ide_conv_dir)
        db_cache = _DB_CACHE.setdefault(cache_key, {})

        for stale_path in set(db_cache) - set(db_files):
            del db_cache[stale_path]

        for db_path in db_files:
            fingerprint = _db_fingerprint(db_path)
            cached = db_cache.get(db_path)
            if cached is not None and cached[0] == fingerprint:
                continue
            db_cache[db_path] = (fingerprint, self._extract_conv_usage(db_path))

        current_files = {}
        for path in db_files:
            usage = db_cache[path][1]
            if usage:
                current_files[path] = usage

        active_state = state if state is not None else self.state
        if active_state is None and self.db_path is None:
            model_totals = {}
            sessions = 0
            for path, usage in current_files.items():
                sessions += 1
                model = usage['model']
                m = model_totals.setdefault(model, {'messages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0})
                m['messages'] += 1
                m['input_tokens'] += usage['input_tokens']
                m['output_tokens'] += usage['output_tokens']
                m['cache_read'] += usage['cache_read']

            return ParserResult(
                sessions=sessions,
                messages=sum(v['messages'] for v in model_totals.values()),
                input_tokens=sum(v['input_tokens'] for v in model_totals.values()),
                output_tokens=sum(v['output_tokens'] for v in model_totals.values()),
                cache_read=sum(v['cache_read'] for v in model_totals.values()),
                cache_write=0,
                models=[
                    ModelUsage(
                        model_name=model,
                        messages=data['messages'],
                        input_tokens=data['input_tokens'],
                        output_tokens=data['output_tokens'],
                        cache_read=data['cache_read'],
                        cache_write=0,
                        cost=0.0,
                    )
                    for model, data in sorted(model_totals.items(), key=lambda x: -x[1]['input_tokens'])
                ]
            )

        if active_state is None:
            files_with_seen = {}
            for path, usage in current_files.items():
                files_with_seen[path] = dict(usage)
                files_with_seen[path]['seen'] = 1
            active_state = {
                'files': files_with_seen,
                'cumulative': {
                    'sessions': len(current_files),
                    'messages': len(current_files),
                    'input_tokens': sum(u['input_tokens'] for u in current_files.values()),
                    'output_tokens': sum(u['output_tokens'] for u in current_files.values()),
                    'cache_read': sum(u['cache_read'] for u in current_files.values()),
                    'models': {}
                }
            }
            for usage in current_files.values():
                model = usage['model']
                m_cum = active_state['cumulative']['models'].setdefault(model, {
                    'messages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0
                })
                m_cum['messages'] += 1
                m_cum['input_tokens'] += usage['input_tokens']
                m_cum['output_tokens'] += usage['output_tokens']
                m_cum['cache_read'] += usage['cache_read']

        prev_files = active_state.get('files', {})
        cum = active_state.get('cumulative', {})

        cum_models = cum.get('models', {})
        stale_keys = [k for k in cum_models if k.startswith(('used_', 'use_', 'enable-', 'disable-')) or 'used_claude' in k]
        stale_files = [f for f, v in prev_files.items() if v.get('model', '').startswith(('used_', 'use_', 'enable-', 'disable-')) or 'used_claude' in v.get('model', '')]
        if stale_keys or stale_files:
            for fval in prev_files.values():
                m = fval.get('model', '')
                if m.startswith(('used_', 'use_', 'enable-', 'disable-')) or 'used_claude' in m:
                    fval['model'] = 'Gemini 3.5 Flash (Low)'
            # Remap stale keys in-place, preserving accumulated totals
            target = 'Gemini 3.5 Flash (Low)'
            for bad_key in stale_keys:
                dst = cum['models'].setdefault(target, {'messages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0})
                for f in ('messages', 'input_tokens', 'output_tokens', 'cache_read'):
                    dst[f] += cum['models'][bad_key][f]
                del cum['models'][bad_key]

        # Handle files that disappear: if a file was seen < 2 times,
        # un-retire it from cumulative (it was never established as real)
        for path, prev in prev_files.items():
            if path not in current_files:
                # File has disappeared. Treat missing 'seen' as established (large number).
                seen_count = prev.get('seen', 999999)
                if seen_count < 2:
                    # This file never proved it was real; subtract its contribution
                    cum['sessions'] = max(0, cum['sessions'] - 1)
                    cum['messages'] = max(0, cum['messages'] - 1)
                    cum['input_tokens'] = max(0, cum['input_tokens'] - prev.get('input_tokens', 0))
                    cum['output_tokens'] = max(0, cum['output_tokens'] - prev.get('output_tokens', 0))
                    cum['cache_read'] = max(0, cum['cache_read'] - prev.get('cache_read', 0))

                    # Also subtract from the model's cumulative
                    model = prev.get('model', '')
                    if model in cum['models']:
                        cum['models'][model]['messages'] = max(0, cum['models'][model]['messages'] - 1)
                        cum['models'][model]['input_tokens'] = max(0, cum['models'][model]['input_tokens'] - prev.get('input_tokens', 0))
                        cum['models'][model]['output_tokens'] = max(0, cum['models'][model]['output_tokens'] - prev.get('output_tokens', 0))
                        cum['models'][model]['cache_read'] = max(0, cum['models'][model]['cache_read'] - prev.get('cache_read', 0))

        delta_sessions = 0
        delta_messages = 0
        delta_input = 0
        delta_output = 0
        delta_cache = 0
        model_deltas = {}

        for path, usage in current_files.items():
            model = usage['model']
            if path not in prev_files:
                delta_sessions += 1
                delta_messages += 1
                di = usage['input_tokens']
                do = usage['output_tokens']
                dc = usage['cache_read']
                dm = 1
            else:
                prev = prev_files[path]
                di = max(0, usage['input_tokens'] - prev['input_tokens'])
                do = max(0, usage['output_tokens'] - prev['output_tokens'])
                dc = max(0, usage['cache_read'] - prev['cache_read'])
                dm = 0

            delta_input += di
            delta_output += do
            delta_cache += dc

            md = model_deltas.setdefault(model, {
                'messages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0
            })
            md['messages'] += dm
            md['input_tokens'] += di
            md['output_tokens'] += do
            md['cache_read'] += dc

        cum['sessions'] += delta_sessions
        cum['messages'] += delta_messages
        cum['input_tokens'] += delta_input
        cum['output_tokens'] += delta_output
        cum['cache_read'] += delta_cache

        for model, md in model_deltas.items():
            m_cum = cum['models'].setdefault(model, {
                'messages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0
            })
            m_cum['messages'] += md['messages']
            m_cum['input_tokens'] += md['input_tokens']
            m_cum['output_tokens'] += md['output_tokens']
            m_cum['cache_read'] += md['cache_read']

        # Update 'seen' counter for each file in current state
        files_with_seen = {}
        for path, usage in current_files.items():
            files_with_seen[path] = dict(usage)
            if path in prev_files and 'seen' in prev_files[path]:
                # File was present before; increment its seen count
                files_with_seen[path]['seen'] = prev_files[path]['seen'] + 1
            else:
                # New file; start at 1
                files_with_seen[path]['seen'] = 1
        active_state['files'] = files_with_seen

        res = ParserResult(
            sessions=cum['sessions'],
            messages=cum['messages'],
            input_tokens=cum['input_tokens'],
            output_tokens=cum['output_tokens'],
            cache_read=cum['cache_read'],
            cache_write=0,
            models=[
                ModelUsage(
                    model_name=model,
                    messages=data['messages'],
                    input_tokens=data['input_tokens'],
                    output_tokens=data['output_tokens'],
                    cache_read=data['cache_read'],
                    cache_write=0,
                    cost=0.0,
                )
                for model, data in sorted(cum['models'].items(), key=lambda x: -x[1]['input_tokens'])
            ]
        )
        self.state = active_state
        res.state = active_state
        return res
