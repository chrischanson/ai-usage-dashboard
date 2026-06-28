"""
Parser for Antigravity (agy) IDE usage data.
Reads all conversation SQLite databases in the agy CLI directory and
extracts per-model token usage from gen_metadata protobuf blobs.
"""
import sqlite3
import glob
import os

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable

AGY_CONV_DIR = os.path.expanduser('~/.gemini/antigravity-cli/conversations')
AGY_IDE_CONV_DIR = os.path.expanduser('~/.gemini/antigravity-ide/conversations')

_MODEL_KEYWORDS = ['gemini', 'claude', 'flash', 'pro', 'sonnet', 'opus',
                   'gpt', 'ultra', 'haiku', 'mistral', 'llama']


class AgyParser(Parser):
    def __init__(self, conv_dir: str = AGY_CONV_DIR, ide_conv_dir: str = AGY_IDE_CONV_DIR):
        self.conv_dir = conv_dir
        self.ide_conv_dir = ide_conv_dir

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
                    try:
                        text = payload.decode('utf-8')
                        results.setdefault(key, []).append(text)
                    except Exception:
                        if depth < 3:
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
        candidates = []
        for vals in fields.values():
            for v in vals:
                if not isinstance(v, str):
                    continue
                vl = v.lower()
                if any(k in vl for k in _MODEL_KEYWORDS) and 3 < len(v) < 60 and '\n' not in v:
                    candidates.append(v)
        if candidates:
            return sorted(candidates, key=len)[0]
        return None

    @staticmethod
    def _extract_conv_usage(db_path: str) -> dict | None:
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

            if not model_name:
                model_name = AgyParser._extract_model_name(f)

        if max_input == 0 and max_output == 0:
            return None

        return {
            'input_tokens': max_input,
            'output_tokens': max_output,
            'cache_read': max_cache,
            'model': model_name or 'unknown',
        }

    def parse(self) -> ParserResult:
        db_dirs = [d for d in [self.conv_dir, self.ide_conv_dir] if os.path.isdir(d)]
        db_files = []
        for d in db_dirs:
            db_files.extend(glob.glob(os.path.join(d, '*.db')))

        if not db_files:
            raise SourceUnavailable("No AGY conversation databases found")

        model_totals: dict[str, dict] = {}
        sessions = 0

        for db_path in db_files:
            usage = self._extract_conv_usage(db_path)
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
            raise SourceUnavailable("No AGY usage data found in conversation databases")

        total_input = sum(v['input_tokens'] for v in model_totals.values())
        total_output = sum(v['output_tokens'] for v in model_totals.values())
        total_cache = sum(v['cache_read'] for v in model_totals.values())

        result = ParserResult(
            sessions=sessions,
            messages=sum(v['messages'] for v in model_totals.values()),
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read=total_cache,
            cache_write=0,
            models=[
                ModelUsage(
                    model_name=model,
                    messages=data['messages'],
                    input_tokens=data['input_tokens'],
                    output_tokens=data['output_tokens'],
                    cache_read=data['cache_read'],
                    cache_write=0,
                    cost=data['cost'],
                )
                for model, data in sorted(model_totals.items(),
                                          key=lambda x: -x[1]['input_tokens'])
            ],
        )

        return result
