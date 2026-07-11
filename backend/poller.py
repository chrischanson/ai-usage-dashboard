import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import fcntl
import logging
import threading
import time
from config import Config
from db import connect, init_schema, record_observation, record_quota, record_status, prune
from source_registry import get_all_sources
from util import parse_iso_seconds

logger = logging.getLogger(__name__)


class Poller:
    """The only writer of usage data. Each cycle it stores every parser's
    raw reading verbatim (see db.record_observation) — all delta/total logic
    happens at read time in db.py.

    start() takes an exclusive flock on a lockfile next to the DB so that a
    second Poller against the same db_path (e.g. a second app instance, or
    uvicorn workers>1) never runs alongside this one and double-writes."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()
        self._lock_fd = None

    def run_once(self, conn) -> None:
        now_sec = int(time.time())
        interval = self.cfg.poll_interval if self.cfg.poll_interval else 600
        cycle_ts = (now_sec // interval) * interval

        for source, entry in get_all_sources().items():
            self._poll_usage(conn, cycle_ts, source, entry)
        self._poll_quota_source(conn, cycle_ts, 'agy', self._collect_agy_quota)
        self._poll_quota_source(conn, cycle_ts, 'opencode', self._collect_opencode_cost)
        self._poll_quota_source(conn, cycle_ts, 'codex', self._collect_codex_quota)
        self._poll_quota_source(conn, cycle_ts, 'claude', self._collect_claude_quota)

        from integrity import check_integrity
        report = check_integrity(conn, interval)
        for warning in report['warnings']:
            print(f"[poller] integrity: {warning}")

        prune(conn, self.cfg.retention_days)

    def start(self) -> None:
        if not self._acquire_lock():
            logger.warning(
                "another poller already holds the lock for db_path=%s; "
                "not starting the polling thread here (this process will "
                "still serve the API off the existing DB)", self.cfg.db_path)
            return

        conn = connect(self.cfg.db_path)
        init_schema(conn)
        conn.close()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _acquire_lock(self) -> bool:
        """Exclusive, non-blocking guard: at most one poller may write a
        given DB at a time. Fails open (returns True with no lock held) for
        ':memory:' DBs and any environment where the lockfile can't even be
        created — an unguarded poller is safer than refusing to start the
        whole app over a lockfile problem in, e.g., a read-only tmp test dir."""
        db_path = self.cfg.db_path
        if db_path == ':memory:':
            return True
        lock_path = db_path + '.poller.lock'
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as e:
            logger.warning(
                "could not create poller lockfile %s (%s); starting "
                "without the single-poller guard", lock_path, e)
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def _loop(self):
        while not self._stop.is_set():
            conn = connect(self.cfg.db_path)
            try:
                self.run_once(conn)
            except Exception as e:
                print(f"[poller] cycle error: {e}")
            finally:
                conn.close()
            self._stop.wait(self.cfg.poll_interval)

    def _poll_usage(self, conn, cycle_ts, source, entry):
        start = time.time()
        try:
            result = entry.parser().parse()
            if result and (result.sessions or result.messages):
                record_observation(conn, source, cycle_ts, result)
                record_status(conn, source, 'usage', cycle_ts, True, None,
                              (time.time() - start) * 1000)
            else:
                record_status(conn, source, 'usage', cycle_ts, False,
                              'empty result', (time.time() - start) * 1000)
        except Exception as e:
            logger.exception("usage poll failed for source=%s", source)
            record_status(conn, source, 'usage', cycle_ts, False, type(e).__name__,
                          (time.time() - start) * 1000)

    def _poll_quota_source(self, conn, cycle_ts, source, collector):
        start = time.time()
        try:
            quota = collector()
            if quota and 'error' not in quota:
                if source == 'opencode':
                    record_quota(conn, 'opencode', cycle_ts, {
                        'opencode': {
                            'total_cost': {
                                'used': quota['total_cost'],
                                'total': 0,
                                'remaining_pct': 100.0,
                                'refreshes_in': 0,
                            }
                        }
                    })
                elif source == 'codex':
                    if 'primary_used_pct' in quota:
                        record_quota(conn, 'codex', cycle_ts, {
                            'openai': {
                                'rate_limit': {
                                    'remaining_pct': 100.0 - quota['primary_used_pct'],
                                    'used': quota['primary_used_pct'],
                                    'total': 100.0,
                                    'refreshes_in_seconds': quota.get('resets_in_seconds', 0),
                                }
                            }
                        })
                    elif 'total_used_usd' in quota:
                        record_quota(conn, 'codex', cycle_ts, {
                            'openai': {
                                'cost': {
                                    'used': quota['total_used_usd'],
                                    'total': quota.get('hard_limit_usd', 0),
                                    'remaining': quota.get('remaining_usd', 0),
                                }
                            }
                        })
                elif source == 'claude':
                    if 'five_hour' in quota:
                        rows = []
                        fh = quota['five_hour']
                        rows.append({
                            'model_group': 'session',
                            'limit_type': 'five_hour',
                            'used': fh.get('utilization', 0),
                            'total': 100.0,
                            'remaining_pct': 100.0 - fh.get('utilization', 0),
                            'refreshes_in_seconds': parse_iso_seconds(fh.get('resets_at', '')),
                        })
                        wd = quota.get('seven_day', {})
                        rows.append({
                            'model_group': 'weekly',
                            'limit_type': 'all_models',
                            'used': wd.get('utilization', 0),
                            'total': 100.0,
                            'remaining_pct': 100.0 - wd.get('utilization', 0),
                            'refreshes_in_seconds': parse_iso_seconds(wd.get('resets_at', '')),
                        })
                        for lim in quota.get('limits', []):
                            if lim.get('kind') == 'weekly_scoped' and lim.get('scope', {}).get('model', {}).get('display_name'):
                                model_name = lim['scope']['model']['display_name']
                                rows.append({
                                    'model_group': 'weekly',
                                    'limit_type': model_name,
                                    'used': lim.get('percent', 0),
                                    'total': 100.0,
                                    'remaining_pct': 100.0 - lim.get('percent', 0),
                                    'refreshes_in_seconds': parse_iso_seconds(lim.get('resets_at', '')),
                                })
                        record_quota(conn, 'claude', cycle_ts, rows)
                else:
                    record_quota(conn, source, cycle_ts, quota)
            else:
                raw_error = quota.get('error', 'empty result') if quota else 'empty result'
                logger.warning("quota poll failed for source=%s: %s", source, raw_error)
                record_status(conn, source, 'quota', cycle_ts, False,
                              raw_error if raw_error == 'empty result' else 'fetch failed',
                              (time.time() - start) * 1000)
                return
            record_status(conn, source, 'quota', cycle_ts, True, None,
                          (time.time() - start) * 1000)
        except Exception as e:
            logger.exception("quota poll failed for source=%s", source)
            record_status(conn, source, 'quota', cycle_ts, False, type(e).__name__,
                          (time.time() - start) * 1000)

    def _collect_agy_quota(self):
        from quota_parser import fetch_agy_quota
        return fetch_agy_quota(network_timeout=self.cfg.network_timeout)

    def _collect_opencode_cost(self):
        from opencode_quota import fetch_opencode_cost
        return fetch_opencode_cost()

    def _collect_codex_quota(self):
        from codex_quota import fetch_codex_quota
        return fetch_codex_quota()

    def _collect_claude_quota(self):
        from claude_quota import fetch_claude_quota
        return fetch_claude_quota()
