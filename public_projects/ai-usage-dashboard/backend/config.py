from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Config:
    db_path: str = field(default_factory=lambda: os.getenv(
        'AQM_DB_PATH',
        os.path.join(os.path.dirname(__file__), 'agy_quota.db')
    ))
    poll_interval: int = 600
    subprocess_timeout: int = 20
    network_timeout: int = 10
    retention_days: int = 90
    host: str = '127.0.0.1'
    port: int = 8000
    log_level: str = 'INFO'


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
        'AQM_DB_PATH',
        os.path.join(os.path.dirname(__file__), 'agy_quota.db')
    )


def load_config() -> Config:
    ll = os.getenv('AQM_LOG_LEVEL', 'INFO')
    if ll not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"AQM_LOG_LEVEL must be one of {''.join(sorted(_VALID_LOG_LEVELS))}, got {ll!r}"
        )
    return Config(
        db_path=_get_default_db_path(),
        poll_interval=_getenv_int('AQM_POLL_INTERVAL', 600),
        subprocess_timeout=_getenv_int('AQM_SUBPROCESS_TIMEOUT', 20),
        network_timeout=_getenv_int('AQM_NETWORK_TIMEOUT', 10),
        retention_days=_getenv_int('AQM_RETENTION_DAYS', 90),
        host=os.getenv('AQM_HOST', '127.0.0.1'),
        port=_getenv_int('AQM_PORT', 8000),
        log_level=ll,
    )
