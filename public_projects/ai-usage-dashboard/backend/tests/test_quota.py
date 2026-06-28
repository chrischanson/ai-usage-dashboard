"""Tests for the unified quota module (quota.py)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from quota import collect
from config import Config, load_config


class TestQuotaCollectSignature(unittest.TestCase):
    def test_collect_is_callable(self):
        self.assertTrue(callable(collect))

    def test_collect_unknown_raises(self):
        cfg = load_config()
        with self.assertRaises(ValueError):
            collect('unknown', cfg)


class TestQuotaCollectLive(unittest.TestCase):
    def test_agy_returns_dict_or_none(self):
        cfg = load_config()
        result = collect('agy', cfg)
        self.assertTrue(isinstance(result, dict) or result is None)

    def test_opencode_returns_dict_or_none(self):
        cfg = load_config()
        result = collect('opencode', cfg)
        self.assertTrue(isinstance(result, dict) or result is None)

    def test_codex_returns_dict_or_none(self):
        cfg = load_config()
        result = collect('codex', cfg)
        self.assertTrue(isinstance(result, dict) or result is None)


class TestQuotaCollectAgyShape(unittest.TestCase):
    def test_agy_shape_has_expected_keys(self):
        from unittest.mock import patch
        with patch('quota_parser.fetch_agy_quota') as mock_fetch:
            mock_fetch.return_value = {
                'gemini_models': {},
                'claude_gpt_models': {},
                'plan': 'Gemini Code Assist',
            }
            cfg = load_config()
            result = collect('agy', cfg)
            self.assertIsNotNone(result)
            self.assertIn('plan', result)
            self.assertIn('gemini_models', result)
            self.assertIn('claude_gpt_models', result)

    def test_agy_returns_none_on_exception(self):
        from unittest.mock import patch
        with patch('quota_parser.fetch_agy_quota') as mock_fetch:
            mock_fetch.side_effect = RuntimeError('rpc failed')
            cfg = load_config()
            result = collect('agy', cfg)
            self.assertIsNone(result)


class TestQuotaCollectOpencodeShape(unittest.TestCase):
    def test_opencode_shape_has_cost_keys(self):
        from unittest.mock import patch
        with patch('quota._collect_opencode') as mock_fn:
            mock_fn.return_value = {
                'total_cost': 42.50,
                'cost_by_model': {'gemini-2.0-flash': 42.50},
            }
            cfg = load_config()
            result = collect('opencode', cfg)
            self.assertIsNotNone(result)
            self.assertIn('total_cost', result)
            self.assertIn('cost_by_model', result)


class TestQuotaCollectCodexShape(unittest.TestCase):
    def test_codex_shape_has_expected_keys(self):
        from unittest.mock import patch
        with patch('codex_quota.fetch_codex_quota') as mock_fetch:
            mock_fetch.return_value = {
                'plan': 'Codex (Plus)',
                'plan_type': 'plus',
                'tokens': {'total_sessions': 10, 'total_tokens': 5000},
            }
            cfg = load_config()
            result = collect('codex', cfg)
            self.assertIsNotNone(result)
            self.assertIn('plan', result)
            self.assertIn('plan_type', result)

    def test_codex_returns_none_on_exception(self):
        from unittest.mock import patch
        with patch('codex_quota.fetch_codex_quota') as mock_fetch:
            mock_fetch.side_effect = RuntimeError('db locked')
            cfg = load_config()
            result = collect('codex', cfg)
            self.assertIsNone(result)


class TestCollectDispatchesToCorrectInternal(unittest.TestCase):
    def test_collect_agy_calls_collect_agy(self):
        from unittest.mock import patch
        with patch('quota._collect_agy') as mock_fn:
            mock_fn.return_value = None
            cfg = load_config()
            collect('agy', cfg)
            mock_fn.assert_called_once()

    def test_collect_opencode_calls_collect_opencode(self):
        from unittest.mock import patch
        with patch('quota._collect_opencode') as mock_fn:
            mock_fn.return_value = None
            cfg = load_config()
            collect('opencode', cfg)
            mock_fn.assert_called_once()

    def test_collect_codex_calls_collect_codex(self):
        from unittest.mock import patch
        with patch('quota._collect_codex') as mock_fn:
            mock_fn.return_value = None
            cfg = load_config()
            collect('codex', cfg)
            mock_fn.assert_called_once()


if __name__ == '__main__':
    unittest.main()
