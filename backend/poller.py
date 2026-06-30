import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import threading
import time
from config import Config
from db import connect, init_schema, insert_usage, insert_quota, record_status


def _filter_stale_quota(conn, source, new_quota):
    """Remove stale parts from new quota data by comparing against DB.

    The language server can cache remainingFraction after a 5-hour window resets,
    returning 0% remaining even when quota has been restored. Per limit, if the
    new data shows dramatically worse remaining_pct than the DB snapshot (more
    than halved), discard that limit — the DB value is likely fresher.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT cycle_ts FROM quota_snapshots WHERE source=? ORDER BY cycle_ts DESC LIMIT 1",
        (source,)
    )
    row = cursor.fetchone()
    if not row:
        return new_quota  # no DB data, trust everything
    cts = row['cycle_ts']
    cursor.execute(
        "SELECT model_group, limit_type, remaining_pct FROM quota_snapshots WHERE source=? AND cycle_ts=?",
        (source, cts)
    )
    db_rows = {(r['model_group'], r['limit_type']): r['remaining_pct'] for r in cursor.fetchall()}

    filtered = {}
    for group_key, limits in new_quota.items():
        if group_key == 'plan' or not isinstance(limits, dict):
            filtered[group_key] = limits
            continue
        filtered[group_key] = {}
        for limit_key, info in limits.items():
            if not isinstance(info, dict):
                filtered[group_key][limit_key] = info
                continue
            key = (group_key, limit_key)
            db_rem = db_rows.get(key)
            new_rem = info.get('remaining_pct', 0)
            if db_rem is not None and db_rem > 10 and new_rem < db_rem * 0.5:
                # New data dropped by more than half while DB shows significant remaining
                # — language server returned stale cached data
                continue
            filtered[group_key][limit_key] = info
    return filtered


class Poller:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()

    def run_once(self, conn) -> None:
        now_sec = int(time.time())
        interval = self.cfg.poll_interval if self.cfg.poll_interval else 600
        cycle_ts = (now_sec // interval) * interval

        self._poll_source(conn, cycle_ts, 'opencode', self._collect_opencode_usage)
        self._poll_source(conn, cycle_ts, 'agy', self._collect_agy_usage)
        self._poll_source(conn, cycle_ts, 'codex', self._collect_codex_usage)
        self._poll_quota_source(conn, cycle_ts, 'agy', self._collect_agy_quota)
        self._poll_quota_source(conn, cycle_ts, 'opencode', self._collect_opencode_cost)
        self._poll_quota_source(conn, cycle_ts, 'codex', self._collect_codex_quota)
        
        from integrity import fix_cycle_integrity
        fix_cycle_integrity(conn, cycle_ts)

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

    def _poll_source(self, conn, cycle_ts, source, collector):
        start = time.time()
        try:
            result = collector()
            if result:
                if isinstance(result, tuple):
                    overview, cost_tokens, models = result
                    sessions = overview.get('Sessions', 0)
                    messages = overview.get('Messages', 0)
                    if sessions or messages:
                        merged = {**overview, **cost_tokens}
                        insert_usage(conn, source, cycle_ts, merged, models)
                else:
                    if result.sessions or result.messages:
                        insert_usage(conn, source, cycle_ts, result, result.models)
            record_status(conn, source, cycle_ts, True, None, (time.time() - start) * 1000)
        except Exception as e:
            record_status(conn, source, cycle_ts, False, str(e), (time.time() - start) * 1000)

    def _poll_quota_source(self, conn, cycle_ts, source, collector):
        start = time.time()
        try:
            quota = collector()
            if quota and 'error' not in quota:
                if source == 'opencode':
                    insert_quota(conn, 'opencode', cycle_ts, {
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
                        insert_quota(conn, 'codex', cycle_ts, {
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
                        insert_quota(conn, 'codex', cycle_ts, {
                            'openai': {
                                'cost': {
                                    'used': quota['total_used_usd'],
                                    'total': quota.get('hard_limit_usd', 0),
                                    'remaining': quota.get('remaining_usd', 0),
                                }
                            }
                        })
                else:
                    filtered = _filter_stale_quota(conn, source, quota)
                    insert_quota(conn, source, cycle_ts, filtered)
            record_status(conn, source, cycle_ts, True, None, (time.time() - start) * 1000)
        except Exception as e:
            record_status(conn, source, cycle_ts, False, str(e), (time.time() - start) * 1000)

    def _collect_opencode_usage(self):
        from parser import fetch_and_parse
        return fetch_and_parse()

    def _collect_agy_usage(self):
        from agy_parser import fetch_agy_usage
        return fetch_agy_usage()

    def _collect_codex_usage(self):
        from codex_parser import fetch_codex_usage
        return fetch_codex_usage()

    def _collect_agy_quota(self):
        from quota_parser import fetch_agy_quota
        return fetch_agy_quota()

    def _collect_opencode_cost(self):
        from opencode_quota import fetch_opencode_cost
        return fetch_opencode_cost()

    def _collect_codex_quota(self):
        from codex_quota import fetch_codex_quota
        return fetch_codex_quota()
