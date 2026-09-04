from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os


@dataclass(frozen=True)
class Config:
    db_path: str = field(default_factory=lambda: os.getenv(
        'USAGE_DB_PATH',
        os.path.join(os.path.dirname(__file__), 'usage.db')
    ))
    poll_interval: int = 600
    subprocess_timeout: int = 20
    network_timeout: int = 10
    retention_days: int = 90
    host: str = '127.0.0.1'
    port: int = 8000
    log_level: str = 'INFO'
    # The Codex CLI used for `codex app-server --stdio` quota reads. A bare
    # name is looked up on PATH and then in the usual install locations; a
    # path is honoured as given. Set USAGE_CODEX_BIN under systemd, where
    # ~/.local/bin is normally absent from PATH.
    codex_bin: str = 'codex'
    # Minimum seconds between live quota collections for one source, however
    # many `?force=true` refreshes arrive. Forced refresh is the only route
    # that spawns a subprocess and calls an upstream API on demand, so it
    # needs a floor even though it deliberately bypasses the read cache.
    force_min_interval: int = 10


_VALID_LOG_LEVELS = frozenset({'DEBUG', 'INFO', 'WARNING', 'ERROR'})


def _getenv_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(
            f"Invalid value for {key}: expected integer, got {raw!r}"
        ) from e


def _get_default_db_path() -> str:
    return os.getenv(
        'USAGE_DB_PATH',
        os.path.join(os.path.dirname(__file__), 'usage.db')
    )


def load_config() -> Config:
    ll = os.getenv('USAGE_LOG_LEVEL', 'INFO')
    if ll not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"USAGE_LOG_LEVEL must be one of {', '.join(sorted(_VALID_LOG_LEVELS))}, got {ll!r}"
        )
    return Config(
        db_path=_get_default_db_path(),
        poll_interval=_getenv_int('USAGE_POLL_INTERVAL', 600),
        subprocess_timeout=_getenv_int('USAGE_SUBPROCESS_TIMEOUT', 20),
        network_timeout=_getenv_int('USAGE_NETWORK_TIMEOUT', 10),
        retention_days=_getenv_int('USAGE_RETENTION_DAYS', 90),
        host=os.getenv('USAGE_HOST', '127.0.0.1'),
        port=_getenv_int('USAGE_PORT', 8000),
        log_level=ll,
        codex_bin=os.getenv('USAGE_CODEX_BIN', 'codex'),
        force_min_interval=_getenv_int('USAGE_FORCE_MIN_INTERVAL', 10),
    )


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line.

    DESIGN specifies structured logs with `source`, `cycle_ts` and
    `duration_ms`; those arrive as `extra=` on the call and are merged in
    when present, so a record without them is still valid JSON.
    """

    _RESERVED = frozenset(vars(logging.LogRecord('', 0, '', 0, '', (), None)))
    _EXTRA_FIELDS = ('source', 'cycle_ts', 'duration_ms', 'kind', 'error_category')

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': datetime.fromtimestamp(record.created, tz=timezone.utc)
                          .isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            # The traceback is one field, not interleaved lines, so a single
            # log record stays a single parseable object.
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = 'INFO') -> None:
    """Install the JSON formatter on the root handler.

    Idempotent: re-running replaces the handler rather than stacking another,
    so a double call cannot duplicate every line.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
