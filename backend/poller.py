import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import fcntl
import logging
import threading
import time
from config import Config
from db import connect, init_schema, record_observation, record_quota, record_status, prune, get_source_state, set_source_state
from source_registry import get_all_sources, get_source
from util import parse_iso_seconds

logger = logging.getLogger(__name__)

# Quota failure categories that mean "this source isn't there right now",
# rather than "something is broken". Antigravity and the Codex CLI are
# user-facing tools, not services, so their local endpoints are legitimately
# absent much of the time. These are logged at info level however often they
# recur; the collection_status row records the failure regardless.
_EXPECTED_UNAVAILABLE = frozenset({
    'not_running',
    'rpc_port_unavailable',
    'binary_not_found',
})


class Poller:
    """The only writer of usage data. Each cycle it hands every parser's
    reading to db.record_observation, which stores it verbatim unless the
    reading looks like tool-state loss (a counter dropping below half its
    previous value), in which case the previous baseline is carried forward
    so the stored series stays cumulative across the reset — see the db.py
    module docstring. All delta/total logic still happens at read time.

    start() takes an exclusive flock on a lockfile next to the DB so that a
    second Poller against the same db_path (e.g. a second app instance, or
    uvicorn workers>1) never runs alongside this one and double-writes."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread = None
        self._lock_fd = None
        # Consecutive quota-poll failure counts per source.
        # Used to downgrade the log level for transient boot-time errors
        # (e.g. AGY language server not yet started) vs. persistent failures.
        self._quota_fail_counts: dict[str, int] = {}

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
            os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
            return True
        except (BlockingIOError, OSError) as e:
            if isinstance(e, BlockingIOError):
                logger.warning(
                    "another poller already holds the lock for db_path=%s; not "
                    "starting the polling thread here (this process will still serve "
                    "the API off the existing DB)", self.cfg.db_path
                )
                self._lock_fd = None
                return False
            else:
                logger.warning(
                    "could not create poller lockfile %s (%s); starting without the "
                    "single-poller guard", lock_path, e
                )
                self._lock_fd = None
                return True

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self._acquire_lock():
            return

        conn = connect(self.cfg.db_path)
        init_schema(conn)
        conn.close()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def run_once(self, conn):
        now = time.time()
        cycle_ts = (int(now) // self.cfg.poll_interval) * self.cfg.poll_interval
        init_schema(conn)

        sources = get_all_sources()
        for name, entry in sources.items():
            if entry.parser:
                self._poll_usage(conn, cycle_ts, name, entry)
            if entry.quota_collector:
                self._poll_quota_source(conn, cycle_ts, name, entry.quota_collector)

        # Keep the 'Unattributed' series continuous for any source that already
        # carries one. Totals are derived as deltas, so a row that appears on
        # some cycles and not others produces a phantom spike where it appears
        # and a clamped drop where it vanishes. Sources without the series are
        # untouched — this never introduces it, only maintains it, which is why
        # enabling it required the one-time history backfill first.
        try:
            from integrity import (backfill_unattributed,
                                   sources_with_attribution_series)
            existing = sources_with_attribution_series(conn)
            if existing:
                backfill_unattributed(conn, sources=existing, cycle_ts=cycle_ts)
        except Exception as e:
            print(f"[poller] attribution upkeep error: {e}")

        prune(conn, self.cfg.retention_days)

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
            state = get_source_state(conn, source)
            parser = entry.parser()
            if hasattr(parser, 'state'):
                parser.state = state
            result = parser.parse()
            res_state = getattr(result, 'state', None)
            if isinstance(res_state, dict):
                set_source_state(conn, source, res_state)
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
        """Collect one source's quota for this cycle.

        A source that reports `quota_error` succeeded partially: something
        (usually the plan) is still worth storing, but the quota read failed.
        """
        start = time.time()
        try:
            quota = collector()
            # A collector may succeed partially: the plan is readable but the
            # quota read itself failed. That is reported as `quota_error`, so
            # the plan can still be persisted while the cycle is recorded as a
            # quota failure rather than a false success.
            partial_error = quota.get('quota_error') if isinstance(quota, dict) else None
            category = quota.get('error_category') if isinstance(quota, dict) else None
            if quota and 'error' not in quota:
                entry = get_source(source)
                normalized = entry.quota_normalizer(quota) if (entry and entry.quota_normalizer) else quota
                record_quota(conn, source, cycle_ts, normalized)
                if partial_error:
                    fail_count = self._quota_fail_counts.get(source, 0) + 1
                    self._quota_fail_counts[source] = fail_count
                    # Some sources are legitimately absent much of the time --
                    # Antigravity is a desktop editor, not a service, so its
                    # local RPC is gone whenever the app is closed. Warning
                    # about that every cycle trains the reader to ignore the
                    # log; it is reported at info level instead. The status row
                    # still records the failure either way.
                    if category in _EXPECTED_UNAVAILABLE:
                        logger.info("quota unavailable for source=%s: %s", source, partial_error)
                    else:
                        logger.warning("quota poll degraded for source=%s: %s", source, partial_error)
                    # record_quota writes an ok=1 status row at the data layer;
                    # overwrite it so the degraded cycle is not logged as clean.
                    record_status(conn, source, 'quota', cycle_ts, False,
                                  category or 'fetch failed',
                                  (time.time() - start) * 1000)
                    return
            else:
                raw_error = quota.get('error', 'empty result') if quota else 'empty result'
                fail_count = self._quota_fail_counts.get(source, 0) + 1
                self._quota_fail_counts[source] = fail_count
                _TRANSIENT_THRESHOLD = 2
                if fail_count <= _TRANSIENT_THRESHOLD:
                    logger.info(
                        "quota poll for source=%s not yet available (attempt %d/%d): %s",
                        source, fail_count, _TRANSIENT_THRESHOLD, raw_error,
                    )
                else:
                    logger.warning("quota poll failed for source=%s: %s", source, raw_error)
                # Prefer the collector's own safe failure category over the
                # blanket 'fetch failed', which says nothing diagnosable.
                if category:
                    status_error = category
                elif raw_error == 'empty result':
                    status_error = raw_error
                else:
                    status_error = 'fetch failed'
                record_status(conn, source, 'quota', cycle_ts, False, status_error,
                              (time.time() - start) * 1000)
                return
            self._quota_fail_counts[source] = 0
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
        return fetch_codex_quota(codex_bin=self.cfg.codex_bin,
                                 timeout=self.cfg.network_timeout)

    def _collect_claude_quota(self):
        from claude_quota import fetch_claude_quota
        return fetch_claude_quota()
