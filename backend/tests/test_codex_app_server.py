"""Tests for the Codex App Server JSON-RPC client (`_AppServerSession` and
`fetch_app_server_rate_limits` in codex_quota.py).

Every test here fakes `subprocess.Popen` -- the real `codex` binary is never
invoked. A `_FakeProcess` stands in for the child: its `.stdout` is fed
pre-scripted lines (or blocks forever, for the timeout case), and its
`.stdin`/`.terminate`/`.kill`/`.wait` are recorded so tests can assert the
child was always reaped, on both the success and failure paths.
"""
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from codex_quota import _AppServerSession, fetch_app_server_rate_limits, CodexQuotaError


class _FakeStdin:
    def __init__(self):
        self.closed = False
        self.writes = []

    def write(self, data):
        if self.closed:
            raise BrokenPipeError('stdin closed')
        self.writes.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeStdout:
    """An iterable stdin-like object; `for line in stdout` is how the real
    session drains it, so this only needs to support iteration + close()."""

    def __init__(self, lines=(), block=False):
        self._lines = list(lines)
        self._idx = 0
        self._block = block
        self.closed = False
        self._unblock = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        if self._block and not self._unblock.is_set():
            # Bounded so a leaked daemon thread can't hang around forever,
            # but long enough that no test's small timeout will ever race it.
            self._unblock.wait(30)
        if self._idx >= len(self._lines):
            raise StopIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line

    def close(self):
        self.closed = True
        self._unblock.set()


class _FakeProcess:
    def __init__(self, lines=(), block_stdout=False):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(lines, block=block_stdout)
        self.terminate_called = False
        self.kill_called = False
        self.wait_calls = 0

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        return 0


def _line(obj) -> str:
    return json.dumps(obj) + '\n'


def _patched_popen(fake_proc):
    return patch('codex_quota.subprocess.Popen', side_effect=lambda *a, **k: fake_proc)


class TestSuccessfulRoundTrip(unittest.TestCase):
    def test_initialize_then_read_rate_limits(self):
        rate_limits_result = {'rateLimits': {'limitId': 'codex', 'primary': {
            'usedPercent': 12, 'windowDurationMins': 43200, 'resetsAt': 1789514532,
        }}}
        fake_proc = _FakeProcess(lines=[
            _line({'jsonrpc': '2.0', 'id': 1, 'result': {}}),
            _line({'jsonrpc': '2.0', 'id': 2, 'result': rate_limits_result}),
        ])
        with _patched_popen(fake_proc):
            result = fetch_app_server_rate_limits('fake-codex', timeout=5)

        self.assertEqual(result, rate_limits_result)
        # initialize, then the notification, then the actual read.
        sent = [json.loads(w) for w in fake_proc.stdin.writes]
        self.assertEqual(sent[0]['method'], 'initialize')
        self.assertEqual(sent[0]['id'], 1)
        self.assertEqual(sent[1]['method'], 'initialized')
        self.assertNotIn('id', sent[1])
        self.assertEqual(sent[2]['method'], 'account/rateLimits/read')
        self.assertEqual(sent[2]['id'], 2)

        self.assertTrue(fake_proc.terminate_called)
        self.assertGreaterEqual(fake_proc.wait_calls, 1)
        self.assertTrue(fake_proc.stdin.closed)


class TestErrorObject(unittest.TestCase):
    def test_jsonrpc_error_response_raises_protocol_error(self):
        long_token = 'a' * 50
        fake_proc = _FakeProcess(lines=[
            _line({'jsonrpc': '2.0', 'id': 1, 'error': {
                'message': f'boom near /a/b/c/d/e {long_token}'}}),
        ])
        with _patched_popen(fake_proc):
            with self.assertRaises(CodexQuotaError) as cm:
                with _AppServerSession('fake-codex', 5) as session:
                    session.request('initialize', {})

        self.assertEqual(cm.exception.category, 'protocol_error')
        self.assertNotIn(long_token, cm.exception.message)
        self.assertTrue(fake_proc.terminate_called)
        self.assertGreaterEqual(fake_proc.wait_calls, 1)


class TestMalformedLine(unittest.TestCase):
    def test_line_starting_with_brace_but_invalid_json_is_fatal(self):
        fake_proc = _FakeProcess(lines=['{not valid json at all\n'])
        with _patched_popen(fake_proc):
            with self.assertRaises(CodexQuotaError) as cm:
                with _AppServerSession('fake-codex', 5) as session:
                    session.request('initialize', {})

        self.assertEqual(cm.exception.category, 'protocol_error')
        self.assertTrue(fake_proc.terminate_called)
        self.assertGreaterEqual(fake_proc.wait_calls, 1)


class TestNonJsonChatterIgnored(unittest.TestCase):
    def test_non_brace_line_is_ignored_not_fatal(self):
        fake_proc = _FakeProcess(lines=[
            'some banner text that is not protocol traffic\n',
            _line({'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True}}),
        ])
        with _patched_popen(fake_proc):
            with _AppServerSession('fake-codex', 5) as session:
                result = session.request('initialize', {})

        self.assertEqual(result, {'ok': True})
        self.assertTrue(fake_proc.terminate_called)
        self.assertGreaterEqual(fake_proc.wait_calls, 1)


class TestInterleavedNotification(unittest.TestCase):
    def test_notification_without_id_is_skipped(self):
        fake_proc = _FakeProcess(lines=[
            _line({'jsonrpc': '2.0', 'method': 'remoteControl/status/changed', 'params': {}}),
            _line({'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True}}),
        ])
        with _patched_popen(fake_proc):
            with _AppServerSession('fake-codex', 5) as session:
                result = session.request('initialize', {})

        self.assertEqual(result, {'ok': True})
        self.assertTrue(fake_proc.terminate_called)


class TestOutOfOrderResponse(unittest.TestCase):
    def test_response_with_different_id_is_skipped(self):
        fake_proc = _FakeProcess(lines=[
            _line({'jsonrpc': '2.0', 'id': 99, 'result': {'wrong': True}}),
            _line({'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True}}),
        ])
        with _patched_popen(fake_proc):
            with _AppServerSession('fake-codex', 5) as session:
                result = session.request('initialize', {})

        self.assertEqual(result, {'ok': True})
        self.assertTrue(fake_proc.terminate_called)


class TestChildExitsWithoutResponding(unittest.TestCase):
    def test_child_eof_before_response_is_protocol_error(self):
        fake_proc = _FakeProcess(lines=[])
        with _patched_popen(fake_proc):
            with self.assertRaises(CodexQuotaError) as cm:
                with _AppServerSession('fake-codex', 5) as session:
                    session.request('initialize', {})

        self.assertEqual(cm.exception.category, 'protocol_error')
        self.assertTrue(fake_proc.terminate_called)
        self.assertGreaterEqual(fake_proc.wait_calls, 1)


class TestTimeout(unittest.TestCase):
    def test_stdout_never_yields_raises_timeout_quickly(self):
        fake_proc = _FakeProcess(block_stdout=True)
        with _patched_popen(fake_proc):
            with self.assertRaises(CodexQuotaError) as cm:
                # Small timeout keeps this test fast; the fake stdout blocks
                # "forever" (bounded internally) so only the deadline ends it.
                with _AppServerSession('fake-codex', 0.2) as session:
                    session.request('initialize', {})

        self.assertEqual(cm.exception.category, 'timeout')
        self.assertTrue(fake_proc.terminate_called)
        self.assertGreaterEqual(fake_proc.wait_calls, 1)


class TestBinaryNotFound(unittest.TestCase):
    def test_popen_file_not_found_maps_to_binary_not_found(self):
        with patch('codex_quota.subprocess.Popen', side_effect=FileNotFoundError()):
            with self.assertRaises(CodexQuotaError) as cm:
                fetch_app_server_rate_limits('missing-codex', timeout=5)

        self.assertEqual(cm.exception.category, 'binary_not_found')


class TestSpawnFailed(unittest.TestCase):
    def test_popen_oserror_maps_to_spawn_failed(self):
        with patch('codex_quota.subprocess.Popen',
                   side_effect=OSError(13, 'Permission denied')):
            with self.assertRaises(CodexQuotaError) as cm:
                fetch_app_server_rate_limits('unusable-codex', timeout=5)

        self.assertEqual(cm.exception.category, 'spawn_failed')


if __name__ == '__main__':
    unittest.main()
