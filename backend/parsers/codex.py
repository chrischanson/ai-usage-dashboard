"""
Parser for OpenAI Codex CLI usage data.
Reads token usage from Codex's SQLite databases.
"""
import glob
import sqlite3
import os
import time

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable

CODEX_STATE_PATTERN = os.path.expanduser('~/.codex/state_*.sqlite')
CODEX_LOGS_PATTERN = os.path.expanduser('~/.codex/logs_*.sqlite')
# Last-known-good fallbacks when no versioned DB exists yet (first run).
CODEX_STATE_DB = os.path.expanduser('~/.codex/state_5.sqlite')
CODEX_LOGS_DB = os.path.expanduser('~/.codex/logs_2.sqlite')

# Per-cycle cache shared with codex_quota._get_token_stats so one poll
# cycle reads state_*.sqlite once instead of twice (usage + quota).
_THREAD_STATS_CACHE: tuple = (0.0, '', None)
_THREAD_STATS_TTL = 660


def resolve_state_db(explicit: str | None = None) -> str:
    """Newest state_*.sqlite, honouring an explicit override (tests/config)."""
    if explicit and explicit not in (CODEX_STATE_DB, CODEX_LOGS_DB):
        return explicit
    if explicit and os.path.isfile(explicit):
        return explicit
    candidates = sorted(glob.glob(CODEX_STATE_PATTERN), reverse=True)
    for path in candidates:
        if os.path.isfile(path):
            return path
    return explicit or CODEX_STATE_DB


def resolve_logs_db(explicit: str | None = None) -> str:
    if explicit and os.path.isfile(explicit):
        return explicit
    candidates = sorted(glob.glob(CODEX_LOGS_PATTERN), reverse=True)
    for path in candidates:
        if os.path.isfile(path):
            return path
    return explicit or CODEX_LOGS_DB


def get_thread_stats(state_db: str | None = None):
    """Single-query thread totals, cached per DB path for one poll cycle.

    Returns (rows, total_sessions, total_tokens) where rows is
    [(model, sessions, tokens), ...] ordered by tokens DESC.
    Raises SourceUnavailable when the DB is missing/unreadable/empty.
    """
    global _THREAD_STATS_CACHE
    db_path = resolve_state_db(state_db)
    now = time.time()
    ts, cached_path, cached = _THREAD_STATS_CACHE
    if cached is not None and cached_path == db_path and (now - ts) < _THREAD_STATS_TTL:
        return cached

    if not os.path.isfile(db_path):
        raise SourceUnavailable(f"Codex state DB not found at {db_path}")

    # mode=ro alone isn't enough: this DB is WAL-mode, and SQLite needs
    # read-write access to its -shm sidecar to open it at all, even for
    # reads. The systemd unit grants that via ReadWritePaths on ~/.codex
    # (see install/usage-dashboard.service) rather than using immutable=1
    # here, which would skip the -wal file entirely and silently miss
    # any codex activity not yet checkpointed into the main db file.
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = conn.execute('''
            SELECT model, COUNT(*) as sessions,
                   COALESCE(SUM(tokens_used), 0) as total_tokens
            FROM threads
            WHERE tokens_used > 0
            GROUP BY model
            ORDER BY total_tokens DESC
        ''').fetchall()
    except Exception as e:
        conn.close()
        raise SourceUnavailable(f"Failed to read Codex state DB: {e}")
    conn.close()

    if not rows:
        raise SourceUnavailable("No Codex usage data found")

    # Totals are derived from the grouped rows — no second COUNT(*)/SUM(*)
    # scan over threads.
    total_sessions = sum(r[1] for r in rows)
    total_tokens = sum(r[2] for r in rows)
    result = (rows, total_sessions, total_tokens)
    _THREAD_STATS_CACHE = (now, db_path, result)
    return result


class CodexParser(Parser):
    def __init__(self, state_db: str = None, logs_db: str = None):
        self.state_db = resolve_state_db(state_db)
        self.logs_db = resolve_logs_db(logs_db)

    def parse(self) -> ParserResult:
        rows, total_sessions, total_tokens = get_thread_stats(self.state_db)

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
