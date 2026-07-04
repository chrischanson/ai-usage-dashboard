"""Tests for the Poller module (poller.py)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import patch, MagicMock
from config import load_config
from poller import Poller
from parsers.base import ParserResult


def _fake_entry(result: ParserResult):
    entry = MagicMock()
    entry.parser.return_value.parse.return_value = result
    return entry


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

    def _run_once_with(self, entries):
        p = Poller(self.cfg)
        with patch('poller.get_all_sources', return_value=entries), \
             patch.object(p, '_collect_agy_quota', return_value={}), \
             patch.object(p, '_collect_opencode_cost', return_value={}), \
             patch.object(p, '_collect_codex_quota', return_value={}), \
             patch.object(p, '_collect_claude_quota', return_value={}):
            p.run_once(self.conn)

    def test_run_once_polls_every_registry_source(self):
        entries = {
            'opencode': _fake_entry(ParserResult()),
            'codex': _fake_entry(ParserResult()),
        }
        self._run_once_with(entries)
        for entry in entries.values():
            entry.parser.return_value.parse.assert_called_once()

    def test_run_once_stores_raw_parser_reading(self):
        entries = {'opencode': _fake_entry(ParserResult(
            sessions=5, messages=10, input_tokens=12345, output_tokens=67890))}
        self._run_once_with(entries)
        row = self.conn.execute(
            "SELECT input_tokens, output_tokens FROM usage_history WHERE source='opencode'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['input_tokens'], 12345)
        self.assertEqual(row['output_tokens'], 67890)

    def test_run_once_records_empty_result_status(self):
        entries = {'opencode': _fake_entry(ParserResult())}
        self._run_once_with(entries)
        row = self.conn.execute(
            "SELECT ok, error FROM collection_status WHERE source='opencode' AND kind='usage'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['ok'], 0)
        self.assertEqual(row['error'], 'empty result')
        count = self.conn.execute("SELECT COUNT(*) FROM usage_history").fetchone()[0]
        self.assertEqual(count, 0)

    def test_run_once_records_parser_failure_status(self):
        # Only the exception's type is persisted/exposed (not str(e)), so a
        # message carrying e.g. an absolute path never reaches /metrics.
        entry = MagicMock()
        entry.parser.return_value.parse.side_effect = RuntimeError('boom /home/alice/secret')
        self._run_once_with({'codex': entry})
        row = self.conn.execute(
            "SELECT ok, error FROM collection_status WHERE source='codex' AND kind='usage'"
        ).fetchone()
        self.assertEqual(row['ok'], 0)
        self.assertEqual(row['error'], 'RuntimeError')


if __name__ == '__main__':
    unittest.main()
