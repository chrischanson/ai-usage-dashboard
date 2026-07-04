import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

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
    happens at read time in db.py."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()

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
        conn = connect(self.cfg.db_path)
        init_schema(conn)
        conn.close()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()

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
        return fetch_agy_quota()

    def _collect_opencode_cost(self):
        from opencode_quota import fetch_opencode_cost
        return fetch_opencode_cost()

    def _collect_codex_quota(self):
        from codex_quota import fetch_codex_quota
        return fetch_codex_quota()

    def _collect_claude_quota(self):
        from claude_quota import fetch_claude_quota
        return fetch_claude_quota()
