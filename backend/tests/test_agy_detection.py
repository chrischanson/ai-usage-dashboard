"""Regression tests for AGY language-server detection.

Background: AGY quota collection looked flaky -- 1018 failures against 7805
successes, in bursts of whole days at 100%. It was not flaky. Two defects
compounded:

1. `_detect_language_server_pids` trusted `pgrep -f`, which matches any
   process whose *command line* contains the pattern. The poller's own shell
   nominated itself, so detection "succeeded" with a pid that owns no
   listening socket.
2. That empty result fell through to a fallback that scanned `ss -tln` and
   treated every local listening port above 1024 as a candidate, then POSTed
   a quota RPC body to each over both HTTP and HTTPS -- unrelated services
   included, and addresses on this host's Tailscale interface, which are not
   even loopback.

The burstiness was simply whether Antigravity was open that day. These tests
pin the fixed behaviour: verify a candidate by its executable, accept only
loopback listening sockets, never guess a port, and report unavailability as
its own category instead of a generic failure.
"""

import os
import unittest
from unittest import mock

import quota_parser as q


class TestExeVerification(unittest.TestCase):
    def test_known_names_accepted(self):
        # These are the real installed binaries on a machine with both
        # Antigravity editions plus the CLI:
        #   /opt/antigravity/Antigravity-x64/antigravity
        #   /opt/antigravity-ide/Antigravity-IDE/antigravity-ide
        #   /opt/antigravity/Antigravity-x64/resources/bin/language_server
        #   ~/.local/bin/agy
        for name in ('language_server_linux_x64', 'language_server', 'agy',
                     'antigravity', 'antigravity-ide'):
            self.assertTrue(q._is_language_server_exe(name), name)

    def test_comm_truncation_accepted(self):
        # The kernel caps `comm` at 15 chars, so the long legacy binary shows
        # up truncated. That must still count as a match.
        self.assertEqual(len('language_server'), 15)
        self.assertTrue(q._is_language_server_exe('language_server'))
        self.assertTrue(q._is_language_server_exe('antigravit'))
        # 'antigravity-ide' is exactly 15 chars, so it survives truncation.
        self.assertEqual(len('antigravity-ide'), 15)

    def test_unrelated_executables_rejected(self):
        # The exact false positive that caused the bug: a shell whose command
        # line quoted the pattern.
        for name in ('bash', 'python3', 'sh', 'node', 'code', 'ss', 'pgrep', '',
                     'marathon_tracker'):
            self.assertFalse(q._is_language_server_exe(name), name)

    def test_short_prefix_rejected(self):
        # Too short to be meaningful -- 'a' prefixes both 'agy' and
        # 'antigravity' but identifies neither. 'ant' is the Java build tool.
        for name in ('a', 'an', 'ant', 'antig'):
            self.assertFalse(q._is_language_server_exe(name), name)

    def test_similar_but_unrelated_names_rejected(self):
        for name in ('antivirus', 'language', 'agent', 'lang_server'):
            self.assertFalse(q._is_language_server_exe(name), name)


class TestPidDetection(unittest.TestCase):
    def test_candidate_with_wrong_exe_is_rejected(self):
        with mock.patch.object(q.subprocess, 'check_output', return_value=b'4242\n'), \
             mock.patch.object(q, '_process_exe_name', return_value='bash'), \
             mock.patch.object(q, '_own_pid_lineage', return_value=set()):
            self.assertEqual(q._detect_language_server_pids(), [])

    def test_candidate_with_right_exe_is_accepted(self):
        with mock.patch.object(q.subprocess, 'check_output', return_value=b'4242\n'), \
             mock.patch.object(q, '_process_exe_name', return_value='language_server'), \
             mock.patch.object(q, '_own_pid_lineage', return_value=set()):
            self.assertEqual(q._detect_language_server_pids(), [4242])

    def test_own_lineage_excluded(self):
        with mock.patch.object(q.subprocess, 'check_output', return_value=b'4242\n'), \
             mock.patch.object(q, '_process_exe_name', return_value='agy'), \
             mock.patch.object(q, '_own_pid_lineage', return_value={4242}):
            self.assertEqual(q._detect_language_server_pids(), [])

    def test_lineage_contains_self(self):
        self.assertIn(os.getpid(), q._own_pid_lineage())

    def test_lineage_does_not_exclude_language_server_ancestor(self):
        # When poller runs inside an Antigravity terminal / agy CLI session,
        # an ancestor process is the editor itself (e.g. agy or antigravity).
        # _own_pid_lineage must not add it to the exclusion set.
        current_pid = os.getpid()
        parent_pid = 50000
        grandparent_pid = 40000

        def fake_open(path, *args, **kwargs):
            if path == f"/proc/{current_pid}/stat":
                return mock.mock_open(read_data=f"{current_pid} (python3) S {parent_pid} 1 1")()
            if path == f"/proc/{parent_pid}/stat":
                return mock.mock_open(read_data=f"{parent_pid} (bash) S {grandparent_pid} 1 1")()
            if path == f"/proc/{grandparent_pid}/stat":
                return mock.mock_open(read_data=f"{grandparent_pid} (agy) S 1 1 1")()
            raise FileNotFoundError(path)

        def fake_exe(pid):
            if pid == current_pid:
                return 'python3'
            if pid == parent_pid:
                return 'bash'
            if pid == grandparent_pid:
                return 'agy'
            return ''

        with mock.patch('builtins.open', side_effect=fake_open), \
             mock.patch.object(q, '_process_exe_name', side_effect=fake_exe):
            lineage = q._own_pid_lineage()
            self.assertIn(current_pid, lineage)
            self.assertIn(parent_pid, lineage)
            self.assertNotIn(grandparent_pid, lineage)

    def test_ancestor_language_server_detected(self):
        # A running language server that happens to be an ancestor process must
        # be detected and accepted as a candidate pid.
        current_pid = os.getpid()
        parent_pid = 50000

        def fake_open(path, *args, **kwargs):
            if path == f"/proc/{current_pid}/stat":
                return mock.mock_open(read_data=f"{current_pid} (python3) S {parent_pid} 1 1")()
            raise FileNotFoundError(path)

        def fake_exe(pid):
            if pid == current_pid:
                return 'python3'
            if pid == parent_pid:
                return 'agy'
            return ''

        with mock.patch('builtins.open', side_effect=fake_open), \
             mock.patch.object(q, '_process_exe_name', side_effect=fake_exe), \
             mock.patch.object(q.subprocess, 'check_output', return_value=f'{parent_pid}\n'.encode()):
            self.assertEqual(q._detect_language_server_pids(), [parent_pid])

    def test_pgrep_missing_is_not_fatal(self):
        with mock.patch.object(q.subprocess, 'check_output',
                               side_effect=FileNotFoundError('no pgrep')):
            self.assertEqual(q._detect_language_server_pids(), [])


class TestAddressDecoding(unittest.TestCase):
    def test_ipv4_loopback(self):
        # /proc/net/tcp stores the address as a little-endian word, so
        # 127.0.0.1 appears as 0100007F, not 7F000001.
        addr = q._decode_proc_net_address('0100007F')
        self.assertEqual(str(addr), '127.0.0.1')
        self.assertTrue(addr.is_loopback)

    def test_ipv4_routable_is_not_loopback(self):
        # 100.104.59.77 -- a Tailscale address actually seen being probed.
        addr = q._decode_proc_net_address('4D3B6864')
        self.assertEqual(str(addr), '100.104.59.77')
        self.assertFalse(addr.is_loopback)

    def test_ipv4_wildcard_is_not_loopback(self):
        addr = q._decode_proc_net_address('00000000')
        self.assertEqual(str(addr), '0.0.0.0')
        self.assertFalse(addr.is_loopback)

    def test_ipv6_loopback(self):
        addr = q._decode_proc_net_address('00000000000000000000000001000000')
        self.assertTrue(addr.is_loopback)

    def test_ipv4_mapped_loopback(self):
        addr = q._decode_proc_net_address('0000000000000000FFFF00000100007F')
        self.assertTrue(addr.is_loopback)

    def test_garbage_returns_none(self):
        for bad in ('', 'ZZZZ', '123', 'x' * 32):
            self.assertIsNone(q._decode_proc_net_address(bad), bad)


def _write_net_file(path, rows):
    """Write a /proc/net/tcp-shaped file. Columns: sl, local, rem, st, ... inode."""
    with open(path, 'w') as f:
        f.write('  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n')
        for i, (local, state, inode) in enumerate(rows):
            f.write(f'  {i}: {local} 00000000:0000 {state} 00000000:00000000 00:00000000 '
                    f'00000000  1000        0 {inode} 1 0000 20 0 0 10 0\n')


class TestPortDetection(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.tcp = os.path.join(self.tmp, 'tcp')

    def _ports(self, rows, inodes):
        _write_net_file(self.tcp, rows)
        with mock.patch.object(q, '_PROC_NET_FILES', (self.tcp,)), \
             mock.patch.object(q, '_detect_language_server_pids', return_value=[999]), \
             mock.patch.object(q, '_socket_inodes_for_pids', return_value=inodes):
            return q._detect_language_server_ports()

    def test_loopback_listening_socket_is_returned(self):
        # 0100007F:A431 -> 127.0.0.1:42033, state 0A -> LISTEN
        self.assertEqual(self._ports([('0100007F:A431', '0A', '555')], {'555'}), [42033])

    def test_non_loopback_listening_socket_is_ignored(self):
        # The Tailscale-bound port the old code happily probed.
        self.assertEqual(self._ports([('4D3B6864:A431', '0A', '555')], {'555'}), [])

    def test_wildcard_bind_is_ignored(self):
        self.assertEqual(self._ports([('00000000:A431', '0A', '555')], {'555'}), [])

    def test_established_socket_is_ignored(self):
        # State 01 is ESTABLISHED, not LISTEN.
        self.assertEqual(self._ports([('0100007F:A431', '01', '555')], {'555'}), [])

    def test_socket_owned_by_another_process_is_ignored(self):
        self.assertEqual(self._ports([('0100007F:A431', '0A', '777')], {'555'}), [])

    def test_no_pids_yields_no_ports_and_no_port_scan(self):
        # The removed fallback shelled out to `ss`. Nothing may run a
        # subprocess here, or the guessing behaviour is back.
        with mock.patch.object(q, '_detect_language_server_pids', return_value=[]), \
             mock.patch.object(q.subprocess, 'check_output') as ran:
            self.assertEqual(q._detect_language_server_ports(), [])
            ran.assert_not_called()

    def test_no_inodes_yields_no_ports_and_no_port_scan(self):
        with mock.patch.object(q, '_detect_language_server_pids', return_value=[999]), \
             mock.patch.object(q, '_socket_inodes_for_pids', return_value=set()), \
             mock.patch.object(q.subprocess, 'check_output') as ran:
            self.assertEqual(q._detect_language_server_ports(), [])
            ran.assert_not_called()

    def test_no_hardcoded_fallback_ports_module_attribute(self):
        # Guards against reintroducing a guessed port list.
        self.assertFalse(hasattr(q, '_FALLBACK_PORTS'))


class TestFetchReporting(unittest.TestCase):
    """A closed editor is an expected state, not a collection error, and the
    plan must survive so the dashboard keeps its badge and last snapshot."""

    def test_not_running(self):
        with mock.patch.object(q, '_detect_agy_plan', return_value='Google One AI Pro'), \
             mock.patch.object(q, '_detect_csrf_token', return_value=None), \
             mock.patch.object(q, '_detect_language_server_ports', return_value=[]), \
             mock.patch.object(q, '_detect_language_server_pids', return_value=[]):
            r = q.fetch_agy_quota(network_timeout=5)
        self.assertEqual(r['error_category'], 'not_running')
        self.assertEqual(r['plan'], 'Google One AI Pro')
        # `error` would make the normalizer discard the payload, losing the plan.
        self.assertNotIn('error', r)
        self.assertIn('quota_error', r)

    def test_running_but_no_loopback_port(self):
        with mock.patch.object(q, '_detect_agy_plan', return_value='X'), \
             mock.patch.object(q, '_detect_csrf_token', return_value=None), \
             mock.patch.object(q, '_detect_language_server_ports', return_value=[]), \
             mock.patch.object(q, '_detect_language_server_pids', return_value=[123]):
            r = q.fetch_agy_quota(network_timeout=5)
        self.assertEqual(r['error_category'], 'rpc_port_unavailable')
        self.assertNotIn('not running', r['quota_error'])

    def test_rpc_failure_reports_the_real_reason(self):
        def boom(port, csrf=None, timeout=3, errors=None):
            if errors is not None:
                errors.append('http: Connection refused')
            raise Exception('Failed to connect to RPC on port %s' % port)

        with mock.patch.object(q, '_detect_agy_plan', return_value='X'), \
             mock.patch.object(q, '_detect_csrf_token', return_value=None), \
             mock.patch.object(q, '_detect_language_server_ports', return_value=[4321]), \
             mock.patch.object(q, '_try_connect_rpc', side_effect=boom):
            r = q.fetch_agy_quota(network_timeout=5)
        self.assertEqual(r['error_category'], 'rpc_unavailable')
        # The generic 'fetch failed' that hid this for weeks is gone.
        self.assertIn('Connection refused', r['quota_error'])
        self.assertEqual(r['plan'], 'X')

    def test_parse_failure_is_its_own_category(self):
        with mock.patch.object(q, '_detect_agy_plan', return_value='X'), \
             mock.patch.object(q, '_detect_csrf_token', return_value=None), \
             mock.patch.object(q, '_detect_language_server_ports', return_value=[4321]), \
             mock.patch.object(q, '_try_connect_rpc',
                               return_value={'response': {'groups': 'not-a-list'}}):
            r = q.fetch_agy_quota(network_timeout=5)
        self.assertEqual(r['error_category'], 'parse_error')
        self.assertEqual(r['plan'], 'X')

    def test_success_returns_groups_and_no_error(self):
        payload = {'response': {'groups': [
            {'displayName': 'Gemini Models', 'buckets': [
                {'bucketId': 'gemini_weekly', 'remainingFraction': 0.25, 'resetTime': ''},
                {'bucketId': 'gemini_5h', 'remainingFraction': 1.0, 'resetTime': ''}]}]}}
        with mock.patch.object(q, '_detect_agy_plan', return_value='X'), \
             mock.patch.object(q, '_detect_csrf_token', return_value=None), \
             mock.patch.object(q, '_detect_language_server_ports', return_value=[4321]), \
             mock.patch.object(q, '_try_connect_rpc', return_value=payload):
            r = q.fetch_agy_quota(network_timeout=5)
        self.assertNotIn('error', r)
        self.assertNotIn('quota_error', r)
        self.assertAlmostEqual(r['gemini_models']['weekly_limit']['remaining_pct'], 25.0)
        self.assertAlmostEqual(r['gemini_models']['weekly_limit']['used'], 75.0)


class TestNormalizerKeepsPlan(unittest.TestCase):
    def test_quota_error_payload_normalizes_to_plan_only(self):
        from providers.scripts.agy_quota import normalize
        result = normalize({
            'plan': 'Google One AI Pro',
            'quota_error': 'Antigravity is not running, so its local quota RPC is unavailable.',
            'error_category': 'not_running',
        })
        # Plan survives; the string fields do not become quota groups.
        self.assertEqual(result, {'_plan': 'Google One AI Pro'})

    def test_hard_error_payload_is_discarded(self):
        from providers.scripts.agy_quota import normalize
        self.assertIsNone(normalize({'error': 'boom'}))


if __name__ == '__main__':
    unittest.main()
