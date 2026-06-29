"""Tests for the Poller module (poller.py)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import load_config
from poller import Poller


class TestPollerConstruction(unittest.TestCase):
    def test_poller_constructs(self):
        cfg = load_config()
        p = Poller(cfg)
        self.assertIsInstance(p, Poller)

    def test_poller_has_run_once(self):
        cfg = load_config()
        p = Poller(cfg)
        self.assertTrue(callable(p.run_once))

    def test_poller_has_start(self):
        cfg = load_config()
        p = Poller(cfg)
        self.assertTrue(callable(p.start))

    def test_poller_has_stop(self):
        cfg = load_config()
        p = Poller(cfg)
        self.assertTrue(callable(p.stop))


class TestPollerStop(unittest.TestCase):
    def test_stop_sets_event(self):
        cfg = load_config()
        p = Poller(cfg)
        self.assertFalse(p._stop.is_set())
        p.stop()
        self.assertTrue(p._stop.is_set())

    def test_stop_is_idempotent(self):
        cfg = load_config()
        p = Poller(cfg)
        p.stop()
        p.stop()
        self.assertTrue(p._stop.is_set())


class TestPollerRunOnce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def setUp(self):
        import tempfile
        self.tf = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tf.close()
        from db import connect, init_schema
        self.conn = connect(self.tf.name)
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tf.name)

    def _make_poller(self):
        return Poller(self.cfg)

    def test_run_once_calls_opencode_usage_collector(self):
        from unittest.mock import patch
        p = self._make_poller()
        with patch.object(p, '_collect_opencode_usage') as mock_fn:
            mock_fn.return_value = ({}, {}, [])
            p.run_once(self.conn)
            mock_fn.assert_called_once()

    def test_run_once_calls_agy_usage_collector(self):
        from unittest.mock import patch
        p = self._make_poller()
        with patch.object(p, '_collect_agy_usage') as mock_fn:
            mock_fn.return_value = ({}, {}, [])
            p.run_once(self.conn)
            mock_fn.assert_called_once()

    def test_run_once_calls_codex_usage_collector(self):
        from unittest.mock import patch
        p = self._make_poller()
        with patch.object(p, '_collect_codex_usage') as mock_fn:
            mock_fn.return_value = ({}, {}, [])
            p.run_once(self.conn)
            mock_fn.assert_called_once()

    def test_run_once_calls_agy_quota_collector(self):
        from unittest.mock import patch
        p = self._make_poller()
        with patch.object(p, '_collect_agy_quota') as mock_fn:
            mock_fn.return_value = {}
            p.run_once(self.conn)
            mock_fn.assert_called_once()

    def test_run_once_calls_opencode_cost_collector(self):
        from unittest.mock import patch
        p = self._make_poller()
        with patch.object(p, '_collect_opencode_cost') as mock_fn:
            mock_fn.return_value = {}
            p.run_once(self.conn)
            mock_fn.assert_called_once()

    def test_run_once_calls_codex_quota_collector(self):
        from unittest.mock import patch
        p = self._make_poller()
        with patch.object(p, '_collect_codex_quota') as mock_fn:
            mock_fn.return_value = {}
            p.run_once(self.conn)
            mock_fn.assert_called_once()

    def test_run_once_preserves_tokens_for_tuple_collectors(self):
        from unittest.mock import patch
        p = self._make_poller()
        
        with patch.object(p, '_collect_opencode_usage') as mock_opencode, \
             patch.object(p, '_collect_agy_usage') as mock_agy, \
             patch.object(p, '_collect_codex_usage') as mock_codex:
             
            mock_opencode.return_value = (
                {'Sessions': 5, 'Messages': 10},
                {'Input': 12345, 'Output': 67890},
                []
            )
            mock_agy.return_value = ({}, {}, [])
            mock_codex.return_value = ({}, {}, [])
            
            p.run_once(self.conn)
            
            cursor = self.conn.cursor()
            cursor.execute("SELECT input_tokens, output_tokens FROM usage_history WHERE source='opencode'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['input_tokens'], 12345)
            self.assertEqual(row['output_tokens'], 67890)


if __name__ == '__main__':
    unittest.main()
