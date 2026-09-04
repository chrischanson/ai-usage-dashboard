"""Freshness/force-refresh behaviour of /api/quota/{source}/latest for Codex.

Uses a real FastAPI TestClient against a temp DB, supplied by handing
create_app() a Config that points at it -- no global to monkeypatch -- and
patches the 'codex'
source-registry entry's quota_collector so no real `codex` subprocess is ever
spawned. The collector is the seam between the App Server client and
everything downstream, so faking it here is exactly what the app-server tests
in test_codex_app_server.py already establish is safe to trust.
"""
import dataclasses
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient

import api
import db
import source_registry
from api import create_app
from config import load_config


def _codex_quota(used_pct=25.0, reset_at=None, plan='Codex (Free)'):
    return {
        '_plan': plan,
        'openai': {
            'rate_limit': {
                'used': used_pct, 'total': 100.0, 'remaining_pct': 100.0 - used_pct,
                'refreshes_in_seconds': 500,
                'reset_at': reset_at if reset_at is not None else int(time.time()) + 500,
                'window_minutes': 43200, 'limit_label': 'Monthly',
            }
        },
    }


def _fake_raw_success(used_pct=42.0, plan_type='free'):
    return {
        'plan_type': plan_type,
        'limits': [{
            'key': 'rate_limit', 'bucket_id': 'codex', 'label': '', 'window_kind': 'primary',
            'used_pct': used_pct, 'window_minutes': 43200,
            'reset_at': int(time.time()) + 86400,
            'limit_reached': False, 'reached_type': '', 'spend_control_reached': False,
            'anomalous': False,
        }],
    }


class _CodexQuotaFreshnessBase(unittest.TestCase):
    def setUp(self):
        self.tmp_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(self.tmp_fd)
        # Config is the single source of truth for the database path, so the
        # temp DB is injected rather than patched over a module global.
        self.cfg = dataclasses.replace(load_config(), db_path=self.db_path)

        api._quota_cache.clear()
        # Also module state: the forced-refresh floor would otherwise carry
        # from one test into the next and throttle its first refresh.
        api._last_fetch_attempt.clear()

        self.entry = source_registry.get_source('codex')
        self.assertIsNotNone(self.entry, 'codex source entry missing from registry')
        self._orig_collector = self.entry.quota_collector

        self.app = create_app(self.cfg)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.entry.quota_collector = self._orig_collector
        api._quota_cache.clear()
        # Also module state: the forced-refresh floor would otherwise carry
        # from one test into the next and throttle its first refresh.
        api._last_fetch_attempt.clear()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _persist(self, cycle_ts, normalized):
        conn = db.connect(self.db_path)
        try:
            db.record_quota(conn, 'codex', cycle_ts, normalized)
        finally:
            conn.close()


class TestStoredSnapshotFreshness(_CodexQuotaFreshnessBase):
    def test_recent_snapshot_is_not_stale_and_not_live(self):
        now = int(time.time())
        self._persist(now, _codex_quota())

        resp = self.client.get('/api/quota/codex/latest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        status = data['codex']['_status']
        self.assertFalse(status['live'])
        self.assertIsNotNone(status['observed_at'])
        self.assertAlmostEqual(status['observed_at'], now, delta=5)
        self.assertIsInstance(status['age_seconds'], int)
        self.assertGreaterEqual(status['age_seconds'], 0)
        self.assertFalse(status['stale'])
        self.assertEqual(data['codex']['openai']['rate_limit']['used'], 25.0)

    def test_old_snapshot_is_flagged_stale(self):
        old = int(time.time()) - 3600  # > _STALE_AFTER_SECONDS (1800)
        self._persist(old, _codex_quota())

        resp = self.client.get('/api/quota/codex/latest')
        data = resp.json()
        self.assertTrue(data['codex']['_status']['stale'])
        self.assertFalse(data['codex']['_status']['live'])


class TestForceRefreshSuccess(_CodexQuotaFreshnessBase):
    def test_force_with_succeeding_collector_returns_live_data(self):
        self.entry.quota_collector = lambda: _fake_raw_success(used_pct=42.0)

        resp = self.client.get('/api/quota/codex/latest?force=true')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['codex']['_status']['live'])
        self.assertEqual(data['codex']['openai']['rate_limit']['used'], 42.0)
        self.assertEqual(data['codex']['_plan'], 'free')


class TestForceRefreshFailure(_CodexQuotaFreshnessBase):
    def test_failing_collector_returns_last_snapshot_not_empty(self):
        now = int(time.time())
        self._persist(now, _codex_quota(used_pct=20.0))

        self.entry.quota_collector = lambda: {'error': 'boom', 'error_category': 'binary_not_found'}

        resp = self.client.get('/api/quota/codex/latest?force=true')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('codex', data)
        self.assertNotEqual(data['codex'], {})
        status = data['codex']['_status']
        self.assertFalse(status['live'])
        self.assertEqual(status['error_category'], 'binary_not_found')
        self.assertEqual(data['codex']['openai']['rate_limit']['used'], 20.0)

    def test_failing_collector_with_no_prior_snapshot_invents_nothing(self):
        self.entry.quota_collector = lambda: {'error': 'boom', 'error_category': 'spawn_failed'}

        resp = self.client.get('/api/quota/codex/latest?force=true')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('codex', data)
        codex_data = data['codex']
        # No meters were invented -- only the freshness envelope is present.
        self.assertEqual(set(codex_data.keys()), {'_status'})
        self.assertFalse(codex_data['_status']['live'])
        self.assertEqual(codex_data['_status']['error_category'], 'spawn_failed')

    def test_failed_force_is_not_cached_as_a_success(self):
        self.entry.quota_collector = lambda: {'error': 'boom', 'error_category': 'timeout'}

        self.client.get('/api/quota/codex/latest?force=true')
        self.assertNotIn('codex', api._quota_cache)


class TestPayloadSafety(_CodexQuotaFreshnessBase):
    """Nothing identifying should ever reach the API response, on either the
    success or failure path -- even if a buggy collector handed some back.
    normalize_quota only reads a fixed set of keys off the raw dict, so an
    unexpected field (accountId, an access token, a stderr blob, a real
    filesystem path) must be dropped rather than passed through."""

    def test_success_path_drops_unexpected_identifying_fields(self):
        leaky = _fake_raw_success(used_pct=5.0)
        leaky['accountId'] = 'acct-secret-123456789012345678901234567890'
        leaky['access_token'] = 'sk-verylongsecrettoken1234567890abcdefabcdefabcdef'
        leaky['stderr'] = 'leaked detail at /home/produser/.codex/auth.json'
        self.entry.quota_collector = lambda: leaky

        resp = self.client.get('/api/quota/codex/latest?force=true')
        body = json.dumps(resp.json())
        for forbidden in ('acct-secret', 'sk-verylongsecrettoken', '/home/',
                          'accountId', 'access_token', 'stderr'):
            self.assertNotIn(forbidden, body)

    def test_failure_path_drops_unexpected_identifying_fields(self):
        leaky = {
            'error': 'boom',
            'error_category': 'protocol_error',
            'accountId': 'acct-secret-fail-123456789012345678901234567890',
            'stderr': '/home/produser/.codex/auth.json boom',
        }
        self.entry.quota_collector = lambda: leaky

        resp = self.client.get('/api/quota/codex/latest?force=true')
        body = json.dumps(resp.json())
        for forbidden in ('acct-secret-fail', '/home/', 'accountId', 'stderr'):
            self.assertNotIn(forbidden, body)


if __name__ == '__main__':
    unittest.main()


class TestForceRefreshThrottle(_CodexQuotaFreshnessBase):
    """`?force=true` bypasses the read cache by design, which makes it the one
    route that spawns a subprocess and calls an upstream API on demand. A floor
    between live attempts stops a caller who can reach the port from driving
    one spawn per request."""

    def _counting_collector(self, result):
        calls = []

        def collector():
            calls.append(time.time())
            return result
        return collector, calls

    def test_repeated_forces_collect_once(self):
        collector, calls = self._counting_collector(_fake_raw_success(used_pct=50.0))
        self.entry.quota_collector = collector
        for _ in range(10):
            self.assertEqual(
                self.client.get('/api/quota/codex/latest?force=true').status_code, 200)
        self.assertEqual(len(calls), 1, 'the floor did not collapse repeated refreshes')

    def test_throttled_response_still_returns_live_data(self):
        collector, _calls = self._counting_collector(_fake_raw_success(used_pct=50.0))
        self.entry.quota_collector = collector
        self.client.get('/api/quota/codex/latest?force=true')
        body = self.client.get('/api/quota/codex/latest?force=true').json()['codex']
        # Cached under the floor is at most force_min_interval old, so it is
        # honestly live -- pressing Refresh twice must not degrade the card.
        self.assertTrue(body['_status']['live'])
        self.assertIn('openai', body)

    def test_failing_collector_is_throttled_too(self):
        # The important case: failures are never cached, so keying the floor
        # off the cache alone would leave exactly this path unthrottled.
        collector, calls = self._counting_collector(
            {'error': 'Codex App Server timed out', 'error_category': 'timeout'})
        self.entry.quota_collector = collector
        for _ in range(10):
            self.assertEqual(
                self.client.get('/api/quota/codex/latest?force=true').status_code, 200)
        self.assertEqual(len(calls), 1, 'a failing source can still be hammered')

    def test_throttled_with_no_snapshot_invents_nothing(self):
        collector, _calls = self._counting_collector(
            {'error': 'boom', 'error_category': 'timeout'})
        self.entry.quota_collector = collector
        self.client.get('/api/quota/codex/latest?force=true')
        body = self.client.get('/api/quota/codex/latest?force=true').json()['codex']
        self.assertFalse(body['_status']['live'])
        self.assertEqual(body['_status']['error_category'], 'rate_limited')
        self.assertEqual([k for k in body if not k.startswith('_')], [])

    def test_attempt_allowed_again_once_the_floor_expires(self):
        collector, calls = self._counting_collector(_fake_raw_success(used_pct=50.0))
        self.entry.quota_collector = collector
        self.client.get('/api/quota/codex/latest?force=true')
        self.assertEqual(len(calls), 1)
        api._last_fetch_attempt['codex'] = time.time() - (self.cfg.force_min_interval + 1)
        self.client.get('/api/quota/codex/latest?force=true')
        self.assertEqual(len(calls), 2)

    def test_unforced_reads_never_collect(self):
        collector, calls = self._counting_collector(_fake_raw_success(used_pct=50.0))
        self.entry.quota_collector = collector
        for _ in range(5):
            self.client.get('/api/quota/codex/latest')
        self.assertEqual(len(calls), 0, 'an ordinary read must serve the snapshot')
