"""Config threading and poller lifecycle (findings R8 and R9 in DESIGN.md).

R8: `db.DB_PATH` was a module global read at *import* time, and `api.py` used
it directly. Anything that set `USAGE_DB_PATH` afterwards -- a test, a fixture
-- kept talking to the real database. Config is now the single source of truth
and the app closes over it.

R9c: `main.py` installed SIGTERM/SIGINT handlers that called `poller.stop()`,
but uvicorn replaces those handlers when it runs, so they never fired and the
poller was killed mid-cycle rather than asked to stop. The app's lifespan owns
the poller now.
"""

import dataclasses
import json
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient

import db
from api import create_app
from config import load_config, setup_logging, JsonLogFormatter


class TestConfigIsSourceOfTruth(unittest.TestCase):
    def test_no_import_time_db_path_global(self):
        self.assertFalse(hasattr(db, 'DB_PATH'),
                         'db.DB_PATH is back; thread Config through instead')

    def test_default_db_path_reads_env_at_call_time(self):
        original = os.environ.get('USAGE_DB_PATH')
        try:
            os.environ['USAGE_DB_PATH'] = '/tmp/some-other-place.db'
            self.assertEqual(db.default_db_path(), '/tmp/some-other-place.db')
        finally:
            if original is None:
                os.environ.pop('USAGE_DB_PATH', None)
            else:
                os.environ['USAGE_DB_PATH'] = original

    def test_app_uses_the_config_it_was_given_not_the_real_db(self):
        fd, tmp = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            cfg = dataclasses.replace(load_config(), db_path=tmp)
            real_path = load_config().db_path
            real_size_before = os.path.getsize(real_path) if os.path.exists(real_path) else None

            with TestClient(create_app(cfg)) as client:
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertEqual(client.get('/api/quota/latest').status_code, 200)

            # The temp DB got the schema; the real one was never opened for write.
            conn = db.connect(tmp)
            tables = {r['name'] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertIn('quota_snapshots', tables)
            if real_size_before is not None:
                self.assertEqual(os.path.getsize(real_path), real_size_before)
        finally:
            os.unlink(tmp)


class _FakePoller:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class TestPollerLifecycle(unittest.TestCase):
    def setUp(self):
        fd, self.tmp = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.cfg = dataclasses.replace(load_config(), db_path=self.tmp)

    def tearDown(self):
        os.unlink(self.tmp)

    def test_lifespan_starts_and_stops_the_poller(self):
        poller = _FakePoller()
        app = create_app(self.cfg, poller=poller)
        # Nothing happens until the app actually runs.
        self.assertEqual((poller.started, poller.stopped), (0, 0))
        with TestClient(app) as client:
            self.assertEqual(poller.started, 1)
            self.assertEqual(poller.stopped, 0)
            client.get('/health')
        # Shutdown must stop it -- this is the part the SIGTERM handler never did.
        self.assertEqual(poller.stopped, 1)

    def test_no_poller_is_fine(self):
        app = create_app(self.cfg)
        with TestClient(app) as client:
            self.assertEqual(client.get('/health').status_code, 200)

    def test_main_does_not_install_signal_handlers(self):
        main_src = open(os.path.join(os.path.dirname(__file__), '..', 'main.py')).read()
        self.assertNotIn('signal.signal', main_src,
                         'uvicorn owns signals; stop the poller from the app lifespan')


class TestStructuredLogging(unittest.TestCase):
    """DESIGN's contract for config.py: "log line is valid JSON"."""

    def _format(self, **kwargs):
        record = logging.LogRecord(
            name='poller', level=logging.INFO, pathname=__file__, lineno=1,
            msg=kwargs.pop('msg', 'hello %s'), args=kwargs.pop('args', ('world',)),
            exc_info=kwargs.pop('exc_info', None))
        for key, value in kwargs.items():
            setattr(record, key, value)
        return json.loads(JsonLogFormatter().format(record))

    def test_line_is_valid_json_with_core_fields(self):
        payload = self._format()
        self.assertEqual(payload['msg'], 'hello world')
        self.assertEqual(payload['level'], 'INFO')
        self.assertEqual(payload['logger'], 'poller')
        self.assertIn('ts', payload)

    def test_structured_extras_are_merged(self):
        payload = self._format(source='codex', cycle_ts=1788540000, duration_ms=812.5)
        self.assertEqual(payload['source'], 'codex')
        self.assertEqual(payload['cycle_ts'], 1788540000)
        self.assertEqual(payload['duration_ms'], 812.5)

    def test_absent_extras_are_omitted_not_null(self):
        self.assertNotIn('source', self._format())

    def test_exception_is_one_field_not_extra_lines(self):
        try:
            raise ValueError('boom')
        except ValueError:
            payload = self._format(exc_info=sys.exc_info())
        self.assertIn('ValueError: boom', payload['exc'])

    def test_setup_logging_is_idempotent(self):
        root = logging.getLogger()
        original = list(root.handlers)
        try:
            setup_logging('INFO')
            first = len(root.handlers)
            setup_logging('INFO')
            self.assertEqual(len(root.handlers), first,
                             'repeat calls stack handlers and duplicate every line')
            self.assertIsInstance(root.handlers[0].formatter, JsonLogFormatter)
        finally:
            for handler in list(root.handlers):
                root.removeHandler(handler)
            for handler in original:
                root.addHandler(handler)


if __name__ == '__main__':
    unittest.main()
