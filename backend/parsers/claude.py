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

CLAUDE_HOME = os.path.expanduser('~/.claude')
_CLAUDE_PROJECTS_DIR = os.path.join(CLAUDE_HOME, 'projects')


class ClaudeParser(Parser):
    def __init__(self, projects_dir: str = None):
        self.projects_dir = projects_dir or os.environ.get(
            'USAGE_CLAUDE_DIR',
            os.environ.get('CLAUDE_HOME', _CLAUDE_PROJECTS_DIR)
        )

    def parse(self) -> ParserResult:
        if not os.path.isdir(self.projects_dir):
            raise SourceUnavailable(
                f"Claude projects directory not found: {self.projects_dir}"
            )

        jsonl_files = glob.glob(os.path.join(self.projects_dir, '**', '*.jsonl'), recursive=True)
        if not jsonl_files:
            raise SourceUnavailable("No Claude transcript files found")

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

        for jsonl_path in jsonl_files:
            try:
                with open(jsonl_path, 'r', encoding='utf-8', errors='replace') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        msg_type = entry.get('type')
                        if msg_type != 'assistant':
                            continue

                        message = entry.get('message', {})
                        msg_id = message.get('id')
                        request_id = entry.get('requestId', '')

                        if not msg_id:
                            continue

                        dedup_key = (msg_id, request_id)
                        if dedup_key in seen_message_ids:
                            continue
                        seen_message_ids.add(dedup_key)

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

                        mt = model_totals[model]
                        mt['messages'] += 1
                        mt['input_tokens'] += input_tokens
                        mt['output_tokens'] += output_tokens
                        mt['cache_read'] += cache_read
                        mt['cache_write'] += cache_write
                        total_messages += 1

            except (OSError, PermissionError):
                continue

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
                    cost=0.0,
                )
                for model, data in sorted(
                    model_totals.items(),
                    key=lambda x: -(x[1]['input_tokens'] + x[1]['output_tokens'])
                )
            ],
        )
