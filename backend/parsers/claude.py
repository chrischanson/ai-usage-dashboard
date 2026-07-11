"""
Parser for Claude (Claude Code) usage data.
Reads JSONL transcripts from ~/.claude/projects/**/*.jsonl.
Deduplicates on (message.id, requestId) to handle streaming rewrites.
"""
import glob
import json
import os
from collections import defaultdict

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable
from pricing import estimate_claude_cost

CLAUDE_HOME = os.path.expanduser('~/.claude')
_CLAUDE_PROJECTS_DIR = os.path.join(CLAUDE_HOME, 'projects')

# source_registry builds a brand-new ClaudeParser every poll cycle (see
# _make_claude_parser), so an instance-level cache would be reset each
# cycle and never save any work. This lives at module scope instead, keyed
# by projects_dir so tests using distinct temp dirs never share entries,
# and per-directory by file path -> (fingerprint, events). fingerprint is
# (mtime, size); events is the list of already-filtered usage tuples
# extracted from that file the last time it was read.
_FILE_CACHE: dict = {}


class ClaudeParser(Parser):
    def __init__(self, projects_dir: str = None):
        self.projects_dir = projects_dir or os.environ.get(
            'USAGE_CLAUDE_DIR',
            os.environ.get('CLAUDE_HOME', _CLAUDE_PROJECTS_DIR)
        )

    @staticmethod
    def _extract_file_events(path: str) -> list:
        """Parse one transcript file into filtered usage tuples.

        Only assistant messages with a msg_id, non-empty usage, and nonzero
        tokens are kept — matching the filters `parse()` used to apply
        inline. Cross-file dedup is intentionally NOT applied here; it
        needs a global seen-set built fresh each parse() call, so it's
        done once over all files' cached events, not per file.
        """
        events = []
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if entry.get('type') != 'assistant':
                        continue

                    message = entry.get('message', {})
                    msg_id = message.get('id')
                    if not msg_id:
                        continue
                    request_id = entry.get('requestId', '')

                    usage = message.get('usage', {})
                    if not usage:
                        continue

                    model = message.get('model', 'unknown')
                    input_tokens = usage.get('input_tokens', 0) or 0
                    output_tokens = usage.get('output_tokens', 0) or 0
                    cache_read = usage.get('cache_read_input_tokens', 0) or 0
                    cache_write = usage.get('cache_creation_input_tokens', 0) or 0

                    if input_tokens == 0 and output_tokens == 0:
                        continue

                    events.append((
                        (msg_id, request_id), model,
                        input_tokens, output_tokens, cache_read, cache_write,
                    ))
        except (OSError, PermissionError):
            # Whatever was appended before the failure is kept, same as the
            # old inline loop which mutated shared totals line-by-line and
            # simply stopped on error rather than discarding prior lines.
            pass
        return events

    def parse(self) -> ParserResult:
        if not os.path.isdir(self.projects_dir):
            raise SourceUnavailable(
                f"Claude projects directory not found: {self.projects_dir}"
            )

        jsonl_files = glob.glob(os.path.join(self.projects_dir, '**', '*.jsonl'), recursive=True)
        if not jsonl_files:
            raise SourceUnavailable("No Claude transcript files found")

        file_cache = _FILE_CACHE.setdefault(self.projects_dir, {})

        # Drop entries for files that vanished since the last cycle so the
        # cache doesn't grow unboundedly across renamed/deleted sessions.
        for stale_path in set(file_cache) - set(jsonl_files):
            del file_cache[stale_path]

        for path in jsonl_files:
            try:
                st = os.stat(path)
            except OSError:
                file_cache.pop(path, None)
                continue
            fingerprint = (st.st_mtime, st.st_size)
            cached = file_cache.get(path)
            if cached is not None and cached[0] == fingerprint:
                continue
            file_cache[path] = (fingerprint, self._extract_file_events(path))

        model_totals = defaultdict(lambda: {
            'messages': 0,
            'input_tokens': 0,
            'output_tokens': 0,
            'cache_read': 0,
            'cache_write': 0,
        })

        total_messages = 0
        sessions = len(jsonl_files)
        seen_message_ids = set()

        # Sorted path order makes cross-file dedup winners deterministic.
        # The old code depended on glob()'s filesystem-dependent order,
        # which was never a documented guarantee — sorting is a strict
        # improvement and doesn't change which *set* of messages counts,
        # only (in the rare cross-file duplicate case) which physical copy
        # is picked, and duplicates share identical usage numbers anyway.
        for path in sorted(file_cache):
            _, events = file_cache[path]
            for dedup_key, model, input_tokens, output_tokens, cache_read, cache_write in events:
                if dedup_key in seen_message_ids:
                    continue
                seen_message_ids.add(dedup_key)

                mt = model_totals[model]
                mt['messages'] += 1
                mt['input_tokens'] += input_tokens
                mt['output_tokens'] += output_tokens
                mt['cache_read'] += cache_read
                mt['cache_write'] += cache_write
                total_messages += 1

        if not model_totals:
            raise SourceUnavailable("No Claude usage data found in transcripts")

        total_input = sum(v['input_tokens'] for v in model_totals.values())
        total_output = sum(v['output_tokens'] for v in model_totals.values())
        total_cache_read = sum(v['cache_read'] for v in model_totals.values())
        total_cache_write = sum(v['cache_write'] for v in model_totals.values())

        return ParserResult(
            sessions=sessions,
            messages=total_messages,
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read=total_cache_read,
            cache_write=total_cache_write,
            models=[
                ModelUsage(
                    model_name=model,
                    messages=data['messages'],
                    input_tokens=data['input_tokens'],
                    output_tokens=data['output_tokens'],
                    cache_read=data['cache_read'],
                    cache_write=data['cache_write'],
                    cost=estimate_claude_cost(
                        model, data['input_tokens'], data['output_tokens'],
                        data['cache_read'], data['cache_write']),
                )
                for model, data in sorted(
                    model_totals.items(),
                    key=lambda x: -(x[1]['input_tokens'] + x[1]['output_tokens'])
                )
            ],
        )
