"""Tests for the Codex App Server protocol normalizers in codex_quota.py:

  normalize_app_server_response  -- GetAccountRateLimitsResponse -> internal raw
  normalize_quota                -- internal raw -> API/DB {'_plan', 'openai': {...}}

Response fixtures follow the real schema shape:
    {'rateLimits': {...one RateLimitSnapshot...},
     'rateLimitsByLimitId': {<limitId>: <RateLimitSnapshot>, ...},
     'accountId': '...'}
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from codex_quota import normalize_app_server_response, normalize_quota, _coerce_reset_at


def _bucket(limit_id='codex', limit_name=None, primary=None, secondary=None,
            plan_type='free', spend_control_reached=False, reached_type=None):
    return {
        'limitId': limit_id,
        'limitName': limit_name,
        'primary': primary,
        'secondary': secondary,
        'planType': plan_type,
        'spendControlReached': spend_control_reached,
        'rateLimitReachedType': reached_type,
    }


def _window(used_percent=10.0, window_minutes=43200, resets_at=1789514532):
    return {'usedPercent': used_percent, 'windowDurationMins': window_minutes, 'resetsAt': resets_at}


def _response(rate_limits=None, by_id=None):
    resp = {'accountId': 'acct-should-never-be-read'}
    if rate_limits is not None:
        resp['rateLimits'] = rate_limits
    if by_id is not None:
        resp['rateLimitsByLimitId'] = by_id
    return resp


class TestPrimaryOnly(unittest.TestCase):
    def test_single_bucket_primary_only(self):
        bucket = _bucket(primary=_window(used_percent=94))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))

        self.assertEqual(len(raw['limits']), 1)
        entry = raw['limits'][0]
        self.assertEqual(entry['key'], 'rate_limit')
        self.assertEqual(entry['window_kind'], 'primary')
        self.assertEqual(entry['used_pct'], 94.0)
        self.assertEqual(entry['window_minutes'], 43200)
        self.assertEqual(entry['reset_at'], 1789514532)

        self.assertEqual(raw['plan_type'], 'free')
        self.assertEqual(raw['primary_used_pct'], 94.0)
        self.assertEqual(raw['window_minutes'], 43200)
        self.assertEqual(raw['reset_at'], 1789514532)


class TestPrimaryAndSecondary(unittest.TestCase):
    def test_two_windows_get_distinct_keys(self):
        bucket = _bucket(primary=_window(used_percent=50, window_minutes=43200),
                         secondary=_window(used_percent=5, window_minutes=1440, resets_at=100))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))

        keys = {e['key'] for e in raw['limits']}
        self.assertEqual(keys, {'rate_limit', 'rate_limit_secondary'})
        by_key = {e['key']: e for e in raw['limits']}
        self.assertEqual(by_key['rate_limit']['window_kind'], 'primary')
        self.assertEqual(by_key['rate_limit_secondary']['window_kind'], 'secondary')
        self.assertEqual(by_key['rate_limit_secondary']['used_pct'], 5.0)


class TestDeduplication(unittest.TestCase):
    def test_mirrored_bucket_produces_one_entry(self):
        """`rateLimits` mirrors one entry of `rateLimitsByLimitId` on a live
        server -- the same bucket must not be emitted twice."""
        bucket = _bucket(limit_id='codex', primary=_window(used_percent=30))
        mirrored = _bucket(limit_id='codex', primary=_window(used_percent=30))
        raw = normalize_app_server_response(
            _response(rate_limits=bucket, by_id={'codex': mirrored}))

        self.assertEqual(len(raw['limits']), 1)
        self.assertEqual(raw['limits'][0]['key'], 'rate_limit')

    def test_distinct_limit_ids_each_get_one_entry_and_primary_bucket_leads(self):
        primary_bucket = _bucket(limit_id='codex', primary=_window(used_percent=10))
        other_bucket = _bucket(limit_id='weekly_limit', primary=_window(used_percent=20))
        # Deliberately order 'weekly_limit' first in the map to prove the
        # mirrored `rateLimits` bucket -- not dict order -- decides the head.
        raw = normalize_app_server_response(_response(
            rate_limits=primary_bucket,
            by_id={'weekly_limit': other_bucket, 'codex': primary_bucket}))

        self.assertEqual(len(raw['limits']), 2)
        self.assertEqual(raw['limits'][0]['key'], 'rate_limit')
        self.assertEqual(raw['limits'][0]['used_pct'], 10.0)
        other_keys = {e['key'] for e in raw['limits'][1:]}
        self.assertEqual(other_keys, {'rate_limit_weekly_limit'})


class TestByIdFallback(unittest.TestCase):
    def test_null_by_id_falls_back_to_rate_limits(self):
        bucket = _bucket(primary=_window(used_percent=7))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id=None))
        self.assertEqual(len(raw['limits']), 1)
        self.assertEqual(raw['limits'][0]['used_pct'], 7.0)

    def test_empty_by_id_falls_back_to_rate_limits(self):
        bucket = _bucket(primary=_window(used_percent=8))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))
        self.assertEqual(len(raw['limits']), 1)
        self.assertEqual(raw['limits'][0]['used_pct'], 8.0)


class TestNullPrimaryWindow(unittest.TestCase):
    def test_null_primary_yields_no_meter_but_keeps_plan(self):
        bucket = _bucket(primary=None, secondary=None, plan_type='pro')
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))

        self.assertEqual(raw['limits'], [])
        self.assertEqual(raw['plan_type'], 'pro')
        self.assertNotIn('primary_used_pct', raw)

        normalized = normalize_quota(raw)
        self.assertEqual(normalized, {'_plan': 'pro'})
        self.assertNotIn('openai', normalized)


class TestUnknownPlanType(unittest.TestCase):
    def test_unknown_plan_type_passes_through(self):
        bucket = _bucket(primary=_window(), plan_type='some_future_tier')
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))
        self.assertEqual(raw['plan_type'], 'some_future_tier')
        normalized = normalize_quota(raw)
        self.assertEqual(normalized['_plan'], 'some_future_tier')


class TestGarbageUsedPercentDropsOnlyItsOwnBucket(unittest.TestCase):
    def test_bad_bucket_dropped_without_discarding_sibling(self):
        bad_bucket = _bucket(limit_id='codex', primary={'usedPercent': 'not-a-number',
                                                         'windowDurationMins': 43200,
                                                         'resetsAt': 100})
        good_bucket = _bucket(limit_id='weekly', primary=_window(used_percent=50))
        raw = normalize_app_server_response(_response(
            rate_limits=None, by_id={'codex': bad_bucket, 'weekly': good_bucket}))

        self.assertEqual(len(raw['limits']), 1)
        self.assertEqual(raw['limits'][0]['used_pct'], 50.0)


class TestResetAtCoercion(unittest.TestCase):
    def test_milliseconds_are_coerced_to_seconds(self):
        self.assertEqual(_coerce_reset_at(1789514532000), 1789514532)

    def test_seconds_pass_through_unchanged(self):
        self.assertEqual(_coerce_reset_at(1789514532), 1789514532)

    def test_negative_becomes_zero(self):
        self.assertEqual(_coerce_reset_at(-5), 0)

    def test_zero_stays_zero(self):
        self.assertEqual(_coerce_reset_at(0), 0)

    def test_none_becomes_zero(self):
        self.assertEqual(_coerce_reset_at(None), 0)

    def test_full_pipeline_coerces_milliseconds(self):
        bucket = _bucket(primary=_window(resets_at=1789514532000))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))
        self.assertEqual(raw['limits'][0]['reset_at'], 1789514532)


class TestAnomalousUsedPercent(unittest.TestCase):
    def test_over_100_is_anomalous_and_remaining_clamped(self):
        bucket = _bucket(primary=_window(used_percent=150))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))
        normalized = normalize_quota(raw)
        row = normalized['openai']['rate_limit']
        self.assertEqual(row['used'], 150.0)
        self.assertEqual(row['remaining_pct'], 0.0)
        self.assertTrue(row.get('anomalous'))

    def test_negative_is_anomalous_and_remaining_clamped_to_100(self):
        bucket = _bucket(primary=_window(used_percent=-10))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))
        normalized = normalize_quota(raw)
        row = normalized['openai']['rate_limit']
        self.assertEqual(row['used'], -10.0)
        self.assertEqual(row['remaining_pct'], 100.0)
        self.assertTrue(row.get('anomalous'))

    def test_in_range_is_not_anomalous(self):
        bucket = _bucket(primary=_window(used_percent=50))
        raw = normalize_app_server_response(_response(rate_limits=bucket, by_id={}))
        normalized = normalize_quota(raw)
        row = normalized['openai']['rate_limit']
        self.assertNotIn('anomalous', row)


class TestNormalizeQuotaEdgeCases(unittest.TestCase):
    def test_none_input_returns_none(self):
        self.assertIsNone(normalize_quota(None))

    def test_non_dict_input_returns_none(self):
        self.assertIsNone(normalize_quota('nope'))

    def test_hard_error_returns_none(self):
        self.assertIsNone(normalize_quota({'error': 'boom', 'error_category': 'unavailable'}))

    def test_quota_error_with_plan_still_yields_plan(self):
        # `quota_error` (as opposed to `error`) is not itself gating in
        # normalize_quota; the flat legacy shape below still normalizes.
        raw = {'plan_type': 'plus', 'primary_used_pct': 20.0, 'window_minutes': 1440,
              'reset_at': 12345, 'quota_error': 'stale read'}
        normalized = normalize_quota(raw)
        self.assertEqual(normalized['_plan'], 'plus')
        self.assertIn('rate_limit', normalized['openai'])

    def test_first_entry_keeps_stable_key_and_others_do_not_overwrite(self):
        raw = {
            'plan_type': 'free',
            'limits': [
                {'key': 'rate_limit', 'used_pct': 1.0, 'window_minutes': 43200, 'reset_at': 0,
                 'window_kind': 'primary'},
                {'key': 'rate_limit', 'used_pct': 99.0, 'window_minutes': 1440, 'reset_at': 0,
                 'window_kind': 'primary'},
                {'key': 'rate_limit_other', 'used_pct': 2.0, 'window_minutes': 1440, 'reset_at': 0,
                 'window_kind': 'primary'},
            ],
        }
        normalized = normalize_quota(raw)
        self.assertEqual(normalized['openai']['rate_limit']['used'], 1.0)
        self.assertEqual(normalized['openai']['rate_limit_other']['used'], 2.0)


if __name__ == '__main__':
    unittest.main()
