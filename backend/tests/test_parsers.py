"""Tests for the parsers package — Parser contract, ModelUsage, ParserResult."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from parsers.base import Parser, ParserResult, ModelUsage, SourceUnavailable
from parsers import OpenCodeParser, AgyParser, CodexParser


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
        # OpenCodeParser should raise on missing binary
        parser = OpenCodeParser(timeout=1)
        with self.assertRaises(SourceUnavailable):
            parser.parse()

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


class TestCodexParserInternals(unittest.TestCase):
    def setUp(self):
        self.parser = CodexParser(state_db='/nonexistent/state.sqlite')

    def test_raises_on_missing_db(self):
        with self.assertRaises(SourceUnavailable):
            self.parser.parse()


class TestBackwardCompatibility(unittest.TestCase):
    """Ensure the old wrapper modules still export the expected public API."""

    def test_parser_exports_fetch_and_parse(self):
        from parser import fetch_and_parse
        result = fetch_and_parse()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        overview, cost_tokens, models = result
        self.assertIsInstance(overview, dict)
        self.assertIsInstance(cost_tokens, dict)
        self.assertIsInstance(models, list)

    def test_agy_parser_exports_fetch_agy_usage(self):
        from agy_parser import fetch_agy_usage
        result = fetch_agy_usage()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_codex_parser_exports_fetch_codex_usage(self):
        from codex_parser import fetch_codex_usage
        result = fetch_codex_usage()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)


if __name__ == '__main__':
    unittest.main()
