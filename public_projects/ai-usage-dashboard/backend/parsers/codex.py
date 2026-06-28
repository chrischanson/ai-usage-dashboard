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
