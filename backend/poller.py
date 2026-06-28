import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import threading
import time
from config import Config
from db import connect, init_schema, insert_usage, insert_quota, record_status, prune


class Poller:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()

    def run_once(self, conn) -> None:
        self._poll_source(conn, 'opencode', self._collect_opencode_usage)
        self._poll_source(conn, 'agy', self._collect_agy_usage)
        self._poll_source(conn, 'codex', self._collect_codex_usage)
        self._poll_quota_source(conn, 'agy', self._collect_agy_quota)
        self._poll_quota_source(conn, 'opencode', self._collect_opencode_cost)
        self._poll_quota_source(conn, 'codex', self._collect_codex_quota)
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

    def _poll_source(self, conn, source, collector):
        start = time.time()
        try:
            result = collector()
            if result:
                overview, cost_tokens, models = result
                if overview or cost_tokens:
                    insert_usage(overview, cost_tokens, models, source=source)
            record_status(conn, source, True, None, time.time() - start)
        except Exception as e:
            record_status(conn, source, False, str(e), time.time() - start)

    def _poll_quota_source(self, conn, source, collector):
        start = time.time()
        try:
            quota = collector()
            if quota and 'error' not in quota:
                if source == 'opencode':
                    insert_quota({
                        'opencode': {
                            'total_cost': {
                                'used': quota['total_cost'],
                                'total': 0,
                                'remaining_pct': 100.0,
                                'refreshes_in': 0,
                            }
                        }
                    }, source='opencode')
                elif source == 'codex':
                    if 'primary_used_pct' in quota:
                        insert_quota({
                            'openai': {
                                'rate_limit': {
                                    'remaining_pct': 100.0 - quota['primary_used_pct'],
                                    'used': quota['primary_used_pct'],
                                    'total': 100.0,
                                    'refreshes_in_seconds': quota.get('resets_in_seconds', 0),
                                }
                            }
                        }, source='codex')
                    elif 'total_used_usd' in quota:
                        insert_quota({
                            'openai': {
                                'cost': {
                                    'used': quota['total_used_usd'],
                                    'total': quota.get('hard_limit_usd', 0),
                                    'remaining': quota.get('remaining_usd', 0),
                                }
                            }
                        }, source='codex')
                else:
                    insert_quota(quota, source=source)
            record_status(conn, source, True, None, time.time() - start)
        except Exception as e:
            record_status(conn, source, False, str(e), time.time() - start)

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
