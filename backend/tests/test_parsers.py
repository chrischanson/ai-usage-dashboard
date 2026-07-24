"""Tests for the parsers package — Parser contract, ModelUsage, ParserResult."""
import unittest
import os
import sys
import json
import shutil
import sqlite3
import tempfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from parsers.base import Parser, ParserResult, ModelUsage, SourceUnavailable
from parsers import OpenCodeParser, AgyParser, CodexParser, ClaudeParser
from parsers.agy import _db_fingerprint
from setup_mock_sources import build_agy_protobuf


class TestModelUsage(unittest.TestCase):
    def test_defaults(self):
        m = ModelUsage(model_name='test-model')
        self.assertEqual(m.model_name, 'test-model')
        self.assertEqual(m.messages, 0)
        self.assertEqual(m.input_tokens, 0)
        self.assertEqual(m.output_tokens, 0)
        self.assertEqual(m.cache_read, 0)
        self.assertEqual(m.cache_write, 0)
        self.assertEqual(m.cost, 0.0)

    def test_custom_values(self):
        m = ModelUsage(
            model_name='gemini-2.0-flash',
            messages=10,
            input_tokens=1000,
            output_tokens=500,
            cache_read=200,
            cache_write=50,
            cost=0.05,
        )
        self.assertEqual(m.model_name, 'gemini-2.0-flash')
        self.assertEqual(m.messages, 10)
        self.assertEqual(m.input_tokens, 1000)
        self.assertEqual(m.output_tokens, 500)
        self.assertEqual(m.cache_read, 200)
        self.assertEqual(m.cache_write, 50)
        self.assertEqual(m.cost, 0.05)


class TestParserResult(unittest.TestCase):
    def test_defaults(self):
        r = ParserResult()
        self.assertEqual(r.sessions, 0)
        self.assertEqual(r.messages, 0)
        self.assertEqual(r.input_tokens, 0)
        self.assertEqual(r.output_tokens, 0)
        self.assertEqual(r.cache_read, 0)
        self.assertEqual(r.cache_write, 0)
        self.assertEqual(r.models, [])

    def test_custom_values(self):
        r = ParserResult(
            sessions=5,
            messages=42,
            input_tokens=10000,
            output_tokens=5000,
            cache_read=2000,
            cache_write=500,
            models=[
                ModelUsage(model_name='m1', messages=20, input_tokens=5000),
                ModelUsage(model_name='m2', messages=22, input_tokens=5000),
            ],
        )
        self.assertEqual(r.sessions, 5)
        self.assertEqual(r.messages, 42)
        self.assertEqual(len(r.models), 2)
        self.assertEqual(r.models[0].model_name, 'm1')
        self.assertEqual(r.models[1].model_name, 'm2')


class TestSourceUnavailable(unittest.TestCase):
    def test_is_exception(self):
        self.assertTrue(issubclass(SourceUnavailable, Exception))

    def test_can_raise_and_catch(self):
        try:
            raise SourceUnavailable("test error")
        except SourceUnavailable as e:
            self.assertEqual(str(e), "test error")

    def test_raised_when_source_missing(self):
        # OpenCodeParser should raise on missing binary. Strip the CI mock
        # bin dir (see setup_mock_sources.py) from PATH for this one check —
        # it's added globally so the *server* has usage data to report, but
        # this test specifically wants opencode genuinely absent.
        parser = OpenCodeParser(timeout=1)
        old_path = os.environ.get('PATH', '')
        os.environ['PATH'] = os.pathsep.join(
            p for p in old_path.split(os.pathsep) if '.ci_mocks' not in p
        )
        try:
            with self.assertRaises(SourceUnavailable):
                parser.parse()
        finally:
            os.environ['PATH'] = old_path

    def test_raised_when_agy_dbs_missing(self):
        parser = AgyParser(conv_dir='/nonexistent/path', ide_conv_dir='/nonexistent/path')
        with self.assertRaises(SourceUnavailable):
            parser.parse()

    def test_raised_when_codex_db_missing(self):
        parser = CodexParser(state_db='/nonexistent/state.sqlite')
        with self.assertRaises(SourceUnavailable):
            parser.parse()


class TestParserABC(unittest.TestCase):
    def test_parser_is_abstract(self):
        with self.assertRaises(TypeError):
            Parser()

    def test_open_code_parser_implements_parse(self):
        parser = OpenCodeParser(timeout=1)
        self.assertIsInstance(parser, Parser)
        self.assertTrue(hasattr(parser, 'parse'))
        self.assertTrue(callable(parser.parse))

    def test_agy_parser_implements_parse(self):
        parser = AgyParser(conv_dir='/nonexistent', ide_conv_dir='/nonexistent')
        self.assertIsInstance(parser, Parser)
        self.assertTrue(hasattr(parser, 'parse'))
        self.assertTrue(callable(parser.parse))

    def test_codex_parser_implements_parse(self):
        parser = CodexParser(state_db='/nonexistent/state.sqlite')
        self.assertIsInstance(parser, Parser)
        self.assertTrue(hasattr(parser, 'parse'))
        self.assertTrue(callable(parser.parse))


class TestOpenCodeParserContent(unittest.TestCase):
    def setUp(self):
        self.parser = OpenCodeParser(timeout=1)

    def test_empty_content(self):
        result = self.parser._parse_content("")
        self.assertIsInstance(result, ParserResult)
        self.assertEqual(result.sessions, 0)
        self.assertEqual(result.models, [])

    def test_malformed_content(self):
        content = "some random text\nwithout any sections\n"
        result = self.parser._parse_content(content)
        self.assertIsInstance(result, ParserResult)
        self.assertEqual(result.sessions, 0)

    def test_parse_number_k(self):
        val = self.parser._parse_number("626.2K")
        self.assertAlmostEqual(val, 626200.0)

    def test_parse_number_m(self):
        val = self.parser._parse_number("8.9M")
        self.assertAlmostEqual(val, 8900000.0)

    def test_parse_number_dollar(self):
        val = self.parser._parse_number("$0.00")
        self.assertAlmostEqual(val, 0.0)

    def test_parse_number_comma(self):
        val = self.parser._parse_number("1,992")
        self.assertAlmostEqual(val, 1992.0)

    def test_parse_number_empty(self):
        val = self.parser._parse_number("")
        self.assertAlmostEqual(val, 0)


class TestAgyParserInternals(unittest.TestCase):
    def setUp(self):
        self.parser = AgyParser(conv_dir='/nonexistent', ide_conv_dir='/nonexistent')

    def test_read_varint_simple(self):
        val, pos = self.parser._read_varint(b'\x00', 0)
        self.assertEqual(val, 0)
        self.assertEqual(pos, 1)

    def test_read_varint_multi_byte(self):
        val, pos = self.parser._read_varint(b'\x80\x01', 0)
        self.assertEqual(val, 128)
        self.assertEqual(pos, 2)

    def test_read_varint_max(self):
        val, pos = self.parser._read_varint(b'\xff\xff\xff\xff\x07', 0)
        self.assertEqual(val, 0x7FFFFFFF)
        self.assertEqual(pos, 5)

    def test_extract_model_name_empty(self):
        self.assertIsNone(self.parser._extract_model_name({}))

    def test_extract_model_name_found(self):
        fields = {'1.2': ['gemini-2.0-flash']}
        name = self.parser._extract_model_name(fields)
        self.assertEqual(name, 'gemini-2.0-flash')

    def test_extract_model_name_ignores_telemetry_tags(self):
        fields = {
            '1.20.1': ['used_claude', 'used_claude_conservative', 'used_non_gemini_model'],
            '1.21': ['Gemini 3.5 Flash (Low)'],
            '1.19': ['gemini-3-flash-c'],
        }
        name = self.parser._extract_model_name(fields)
        self.assertEqual(name, 'Gemini 3.5 Flash (Low)')


class TestCodexParserInternals(unittest.TestCase):
    def setUp(self):
        self.parser = CodexParser(state_db='/nonexistent/state.sqlite')

    def test_raises_on_missing_db(self):
        with self.assertRaises(SourceUnavailable):
            self.parser.parse()


def _claude_assistant_line(msg_id, request_id, input_tokens, output_tokens,
                            model='claude-3-5-sonnet-20241022'):
    return {
        'type': 'assistant',
        'requestId': request_id,
        'message': {
            'id': msg_id,
            'model': model,
            'usage': {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
            },
        },
    }


class TestClaudeParserCaching(unittest.TestCase):
    """ClaudeParser is rebuilt from scratch every poll cycle (see
    source_registry._make_claude_parser), so its per-file cache has to
    live at module scope keyed by projects_dir. These tests use a fresh
    tempdir per test, so they never collide with each other or with a
    real ~/.claude/projects cache entry."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_path = os.path.join(self.tmpdir, 'session1.jsonl')
        self._write(self.session_path, [_claude_assistant_line('msg-1', 'req-1', 100, 50)])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _write(path, entries, mode='w'):
        with open(path, mode) as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')

    def test_unchanged_file_not_reread(self):
        parser = ClaudeParser(projects_dir=self.tmpdir)
        result1 = parser.parse()

        with mock.patch.object(ClaudeParser, '_extract_file_events',
                                wraps=ClaudeParser._extract_file_events) as spy:
            result2 = parser.parse()
            spy.assert_not_called()

        self.assertEqual(result1.input_tokens, result2.input_tokens)
        self.assertEqual(result1.messages, result2.messages)
        self.assertEqual(result2.input_tokens, 100)
        self.assertEqual(result2.sessions, 1)

    def test_modified_file_is_reread_and_result_updates(self):
        other_path = os.path.join(self.tmpdir, 'session2.jsonl')
        self._write(other_path, [_claude_assistant_line('msg-2', 'req-2', 10, 5)])

        parser = ClaudeParser(projects_dir=self.tmpdir)
        result1 = parser.parse()
        self.assertEqual(result1.input_tokens, 110)
        self.assertEqual(result1.messages, 2)

        # Only session1.jsonl changes; session2.jsonl must be served from cache.
        self._write(self.session_path, [_claude_assistant_line('msg-3', 'req-3', 20, 8)], mode='a')

        with mock.patch.object(ClaudeParser, '_extract_file_events',
                                wraps=ClaudeParser._extract_file_events) as spy:
            result2 = parser.parse()
            reread_paths = [call.args[0] for call in spy.call_args_list]
            self.assertEqual(reread_paths, [self.session_path])

        self.assertEqual(result2.input_tokens, 130)
        self.assertEqual(result2.messages, 3)
        self.assertEqual(result2.sessions, 2)

    def test_cross_file_dedup_holds_when_only_one_file_changes(self):
        # Same (msg.id, requestId) duplicated across two files, e.g. a
        # resumed/forked session — must count once no matter which of the
        # two files' cache entries happens to be fresh.
        dup_entry = _claude_assistant_line('msg-dup', 'req-dup', 500, 200)
        path_a = os.path.join(self.tmpdir, 'a.jsonl')
        path_b = os.path.join(self.tmpdir, 'b.jsonl')
        self._write(path_a, [dup_entry])
        self._write(path_b, [dup_entry])

        parser = ClaudeParser(projects_dir=self.tmpdir)
        result1 = parser.parse()
        # session1 (100) + the duplicate counted once (500)
        self.assertEqual(result1.input_tokens, 600)
        self.assertEqual(result1.messages, 2)

        # Only b.jsonl changes; a.jsonl (holding the other half of the
        # duplicate) is served from cache and must not cause double counting.
        self._write(path_b, [_claude_assistant_line('msg-4', 'req-4', 7, 3)], mode='a')

        result2 = parser.parse()
        self.assertEqual(result2.input_tokens, 607)
        self.assertEqual(result2.messages, 3)

    def test_deleted_file_drops_from_cache_and_totals(self):
        parser = ClaudeParser(projects_dir=self.tmpdir)
        parser.parse()

        os.remove(self.session_path)
        other_path = os.path.join(self.tmpdir, 'session2.jsonl')
        self._write(other_path, [_claude_assistant_line('msg-2', 'req-2', 10, 5)])

        result = parser.parse()
        self.assertEqual(result.input_tokens, 10)
        self.assertEqual(result.sessions, 1)


def _write_agy_db(path, input_tokens, output_tokens, cache_read, model, idx=0):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS gen_metadata (idx INTEGER, data BLOB)')
    blob = build_agy_protobuf(input_tokens=input_tokens, output_tokens=output_tokens,
                               cache_read=cache_read, model_name=model)
    conn.execute('INSERT INTO gen_metadata (idx, data) VALUES (?, ?)', (idx, blob))
    conn.commit()
    conn.close()


class TestAgyParserCaching(unittest.TestCase):
    """Same rebuild-every-cycle situation as ClaudeParser (see
    source_registry._make_agy_parser); AgyParser's cache also has to be
    module-scoped, keyed by (conv_dir, ide_conv_dir) so temp-dir-backed
    tests stay isolated from each other."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.conv_dir = os.path.join(self.tmpdir, 'conv')
        self.ide_dir = os.path.join(self.tmpdir, 'ide')
        os.makedirs(self.conv_dir)
        os.makedirs(self.ide_dir)
        self.db_path = os.path.join(self.conv_dir, 'conv1.db')
        _write_agy_db(self.db_path, input_tokens=1000, output_tokens=200,
                       cache_read=50, model='claude-sonnet')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unchanged_db_not_rescanned(self):
        parser = AgyParser(conv_dir=self.conv_dir, ide_conv_dir=self.ide_dir)
        result1 = parser.parse()

        with mock.patch.object(AgyParser, '_extract_conv_usage',
                                wraps=AgyParser._extract_conv_usage) as spy:
            result2 = parser.parse()
            spy.assert_not_called()

        self.assertEqual(result1.input_tokens, result2.input_tokens)
        self.assertEqual(result1.sessions, result2.sessions)
        self.assertEqual(result2.input_tokens, 1000)

    def test_modified_db_is_rescanned_and_result_updates(self):
        parser = AgyParser(conv_dir=self.conv_dir, ide_conv_dir=self.ide_dir)
        result1 = parser.parse()
        self.assertEqual(result1.input_tokens, 1000)

        # New blob (different length) -> mtime/size fingerprint changes.
        _write_agy_db(self.db_path, input_tokens=5000, output_tokens=900,
                       cache_read=75, model='claude-opus')
        st = os.stat(self.db_path)
        os.utime(self.db_path, (st.st_atime, st.st_mtime + 5))

        with mock.patch.object(AgyParser, '_extract_conv_usage',
                                wraps=AgyParser._extract_conv_usage) as spy:
            result2 = parser.parse()
            spy.assert_called_once_with(self.db_path)

        self.assertEqual(result2.input_tokens, 5000)

    def test_db_fingerprint_tracks_wal_and_shm_sidecars(self):
        # Appends in WAL mode land in -wal without touching the main
        # file's mtime/size, so the fingerprint must change anyway —
        # otherwise a growing live conversation would look frozen forever.
        fp_before = _db_fingerprint(self.db_path)

        wal_path = self.db_path + '-wal'
        with open(wal_path, 'wb') as f:
            f.write(b'\x00' * 32)
        fp_with_wal = _db_fingerprint(self.db_path)
        self.assertNotEqual(fp_before, fp_with_wal)

        shm_path = self.db_path + '-shm'
        with open(shm_path, 'wb') as f:
            f.write(b'\x00' * 16)
        fp_with_shm = _db_fingerprint(self.db_path)
        self.assertNotEqual(fp_with_wal, fp_with_shm)

        os.remove(wal_path)
        os.remove(shm_path)
        fp_removed = _db_fingerprint(self.db_path)
        self.assertEqual(fp_removed, fp_before)

    def test_wal_only_append_invalidates_cache_without_touching_main_file(self):
        # End-to-end version of the fingerprint test above: a live writer
        # connection appends a second row via WAL; the main .db file's
        # mtime/size must stay identical while the -wal sidecar carries
        # the new data, and AgyParser must still pick it up.
        wal_db = os.path.join(self.conv_dir, 'wal_conv.db')
        writer = sqlite3.connect(wal_db)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE IF NOT EXISTS gen_metadata (idx INTEGER, data BLOB)')
            blob1 = build_agy_protobuf(input_tokens=1000, output_tokens=200,
                                        cache_read=0, model_name='claude-sonnet')
            writer.execute('INSERT INTO gen_metadata (idx, data) VALUES (0, ?)', (blob1,))
            writer.commit()

            parser = AgyParser(conv_dir=self.conv_dir, ide_conv_dir=self.ide_dir)
            result1 = parser.parse()
            self.assertEqual(result1.input_tokens, 1000 + 1000)  # + setUp's conv1.db

            stat_before = os.stat(wal_db)

            blob2 = build_agy_protobuf(input_tokens=9000, output_tokens=800,
                                        cache_read=0, model_name='claude-sonnet')
            writer.execute('INSERT INTO gen_metadata (idx, data) VALUES (1, ?)', (blob2,))
            writer.commit()

            stat_after = os.stat(wal_db)
            self.assertEqual(
                (stat_before.st_mtime, stat_before.st_size),
                (stat_after.st_mtime, stat_after.st_size),
                "test setup assumption broken: main file changed, no longer exercises WAL-only growth",
            )
            self.assertTrue(os.path.exists(wal_db + '-wal'))

            result2 = parser.parse()
            # wal_conv.db's usage grows from 1000 to 9000 (max per row, not
            # summed); conv1.db from setUp is unchanged at 1000.
            self.assertEqual(result2.input_tokens, 9000 + 1000)
        finally:
            writer.close()

    def test_deleted_db_drops_from_cache_and_totals(self):
        parser = AgyParser(conv_dir=self.conv_dir, ide_conv_dir=self.ide_dir)
        parser.parse()

        os.remove(self.db_path)
        other_path = os.path.join(self.conv_dir, 'conv2.db')
        _write_agy_db(other_path, input_tokens=42, output_tokens=7,
                       cache_read=0, model='claude-haiku')

        result = parser.parse()
        self.assertEqual(result.input_tokens, 42)
        self.assertEqual(result.sessions, 1)


class TestAgyParserCumulative(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.conv_dir = os.path.join(self.tmp_dir, 'conv')
        self.ide_dir = os.path.join(self.tmp_dir, 'ide')
        os.makedirs(self.conv_dir)
        os.makedirs(self.ide_dir)
        
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(self.db_fd)
        
        from db import init_schema
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        self.conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_cumulative_delta_tracking(self):
        conv1 = os.path.join(self.conv_dir, 'conv1.db')
        _write_agy_db(conv1, input_tokens=100, output_tokens=20, cache_read=0, model='claude-sonnet')
        
        parser = AgyParser(conv_dir=self.conv_dir, ide_conv_dir=self.ide_dir, db_path=self.db_path)
        res1 = parser.parse()
        self.assertEqual(res1.input_tokens, 100)
        self.assertEqual(res1.sessions, 1)
        self.assertEqual(res1.messages, 1)
        
        # 1. Modify the file (growth)
        _write_agy_db(conv1, input_tokens=150, output_tokens=30, cache_read=0, model='claude-sonnet')
        import time
        os.utime(conv1, (time.time() + 5, time.time() + 5))
        res2 = parser.parse()
        self.assertEqual(res2.input_tokens, 150)
        self.assertEqual(res2.sessions, 1)
        self.assertEqual(res2.messages, 1)
        
        # 2. Add a new file
        conv2 = os.path.join(self.conv_dir, 'conv2.db')
        _write_agy_db(conv2, input_tokens=200, output_tokens=40, cache_read=0, model='gemini-flash')
        res3 = parser.parse()
        self.assertEqual(res3.input_tokens, 350)
        self.assertEqual(res3.sessions, 2)
        self.assertEqual(res3.messages, 2)
        
        # 3. Delete the first file (should NOT drop totals!)
        os.remove(conv1)
        res4 = parser.parse()
        self.assertEqual(res4.input_tokens, 350)
        self.assertEqual(res4.sessions, 2)
        self.assertEqual(res4.messages, 2)


class TestSourceRegistry(unittest.TestCase):
    """All sources are polled through the registry's parser factories."""

    def test_registry_covers_all_sources(self):
        from source_registry import get_all_names
        self.assertEqual(set(get_all_names()), {'opencode', 'agy', 'codex', 'claude'})

    def test_registry_parsers_are_factories(self):
        from source_registry import get_all_sources
        for name, entry in get_all_sources().items():
            self.assertTrue(callable(entry.parser), name)
            self.assertTrue(hasattr(entry.parser(), 'parse'), name)


if __name__ == '__main__':
    unittest.main()
