"""
Parser for OpenAI Codex CLI usage data.
Reads token usage from Codex's SQLite databases.
"""
import sqlite3
import os

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable

CODEX_STATE_DB = os.path.expanduser('~/.codex/state_5.sqlite')
CODEX_LOGS_DB = os.path.expanduser('~/.codex/logs_2.sqlite')


class CodexParser(Parser):
    def __init__(self, state_db: str = CODEX_STATE_DB, logs_db: str = CODEX_LOGS_DB):
        self.state_db = state_db
        self.logs_db = logs_db

    def parse(self) -> ParserResult:
        if not os.path.isfile(self.state_db):
            raise SourceUnavailable(f"Codex state DB not found at {self.state_db}")

        try:
            # mode=ro alone isn't enough: this DB is WAL-mode, and SQLite needs
            # read-write access to its -shm sidecar to open it at all, even for
            # reads. The systemd unit grants that via ReadWritePaths on ~/.codex
            # (see install/usage-dashboard.service) rather than using immutable=1
            # here, which would skip the -wal file entirely and silently miss
            # any codex activity not yet checkpointed into the main db file.
            conn = sqlite3.connect(f'file:{self.state_db}?mode=ro', uri=True)
            rows = conn.execute('''
                SELECT model, COUNT(*) as sessions,
                       COALESCE(SUM(tokens_used), 0) as total_tokens
                FROM threads
                WHERE tokens_used > 0
                GROUP BY model
                ORDER BY total_tokens DESC
            ''').fetchall()

            total_sessions = conn.execute(
                'SELECT COUNT(*) FROM threads WHERE tokens_used > 0'
            ).fetchone()[0]

            total_tokens = conn.execute(
                'SELECT COALESCE(SUM(tokens_used), 0) FROM threads WHERE tokens_used > 0'
            ).fetchone()[0]

            conn.close()
        except Exception as e:
            raise SourceUnavailable(f"Failed to read Codex state DB: {e}")

        if not rows:
            raise SourceUnavailable("No Codex usage data found")

        # output_tokens is hardcoded to 0, not left unimplemented: threads.tokens_used
        # is the only token counter Codex's local state DB exposes (checked the
        # columns directly), and logs_2.sqlite only holds operational tracing spans
        # (rpc method names, no numeric usage bodies) -- there's no local source for
        # a real input/output split, so total_tokens goes into input_tokens instead
        # of guessing a split.
        result = ParserResult(
            sessions=total_sessions,
            messages=total_sessions,
            input_tokens=total_tokens,
            output_tokens=0,
            cache_read=0,
            cache_write=0,
            models=[
                ModelUsage(
                    model_name=model,
                    messages=sessions,
                    input_tokens=tokens,
                    output_tokens=0,
                    cache_read=0,
                    cache_write=0,
                    cost=0.0,
                )
                for model, sessions, tokens in rows
            ],
        )

        return result
