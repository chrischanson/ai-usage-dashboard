"""Tests for the Poller module (poller.py)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import patch, MagicMock
from config import Config, load_config
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


class TestPollerLockGuard(unittest.TestCase):
    """A second Poller pointed at the same db_path must never run a
    competing polling thread — that would double-write the DB (see
    poller.Poller._acquire_lock)."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'guard.db')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cfg(self):
        return Config(db_path=self.db_path)

    def test_second_acquire_lock_fails_while_first_holds_it(self):
        p1 = Poller(self._cfg())
        p2 = Poller(self._cfg())
        self.assertTrue(p1._acquire_lock())
        self.assertFalse(p2._acquire_lock())
        p1.stop()

    def test_stop_releases_lock_for_next_poller(self):
        p1 = Poller(self._cfg())
        p2 = Poller(self._cfg())
        self.assertTrue(p1._acquire_lock())
        p1.stop()
        self.assertTrue(p2._acquire_lock())
        p2.stop()

    def test_second_start_does_not_spawn_a_second_thread(self):
        p1 = Poller(self._cfg())
        p2 = Poller(self._cfg())
        with patch('poller.threading.Thread') as mock_thread:
            p1.start()
            self.assertEqual(mock_thread.call_count, 1)
            p2.start()
            # p2 lost the flock race, so it must not touch threading.Thread again.
            self.assertEqual(mock_thread.call_count, 1)
        p1.stop()

    def test_memory_db_fails_open_no_guard(self):
        # ':memory:' has no on-disk path to lock against, and multiple
        # in-process/test Pollers sharing it are expected (each test builds
        # its own), so the guard is skipped entirely rather than blocking.
        cfg = Config(db_path=':memory:')
        p1 = Poller(cfg)
        p2 = Poller(cfg)
        self.assertTrue(p1._acquire_lock())
        self.assertTrue(p2._acquire_lock())

    def test_unwritable_lock_directory_fails_open(self):
        # A lockfile that can't be created (e.g. read-only parent dir) must
        # not crash the whole app over a guard — better to run unguarded.
        cfg = Config(db_path=os.path.join(self.tmpdir, 'nosuchdir', 'guard.db'))
        p = Poller(cfg)
        self.assertTrue(p._acquire_lock())


class TestOpencodeTimeoutWiring(unittest.TestCase):
    """Config.subprocess_timeout (USAGE_SUBPROCESS_TIMEOUT) must reach the
    OpenCodeParser instance the registry hands to the poller — otherwise the
    env override is dead config (see source_registry._make_opencode_parser)."""

    def test_registry_builds_opencode_parser_with_configured_timeout(self):
        with patch.dict(os.environ, {'USAGE_SUBPROCESS_TIMEOUT': '7'}):
            from source_registry import get_source
            entry = get_source('opencode')
            parser = entry.parser()
            self.assertEqual(parser.timeout, 7)

    def test_registry_opencode_timeout_defaults_match_config_default(self):
        env = {k: v for k, v in os.environ.items() if k != 'USAGE_SUBPROCESS_TIMEOUT'}
        with patch.dict(os.environ, env, clear=True):
            from source_registry import get_source
            entry = get_source('opencode')
            parser = entry.parser()
            self.assertEqual(parser.timeout, load_config().subprocess_timeout)


if __name__ == '__main__':
    unittest.main()
