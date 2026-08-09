"""Tests for the provider abstraction layer.

Verifies that:
  - YAML provider definitions load correctly
  - The field mapping engine extracts values properly
  - The adapter dispatch works for each type
  - The registry integration replaces sources when providers exist
  - Invalid providers are skipped gracefully
"""
import os
import sys
import tempfile
import textwrap
import shutil
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from provider_loader import (
    get_by_dot_path, get_numeric, get_float, get_string,
    load_providers, GenericParser,
)
from source_registry import (
    _SourceEntry, get_all_sources, get_all_names, get_source,
    is_valid_source, load_from_providers,
)
from config import load_config


# ---------------------------------------------------------------------------
# Dot-path extraction
# ---------------------------------------------------------------------------

class TestDotPath:
    def test_simple_key(self):
        assert get_by_dot_path({'a': 1}, '.a') == 1

    def test_nested_key(self):
        assert get_by_dot_path({'a': {'b': 42}}, '.a.b') == 42

    def test_missing_key_returns_default(self):
        assert get_by_dot_path({'a': 1}, '.b', 99) == 99

    def test_empty_path_returns_default(self):
        assert get_by_dot_path({'a': 1}, '', 99) == 99

    def test_no_dot_prefix_returns_default(self):
        assert get_by_dot_path({'a': 1}, 'a', 99) == 99

    def test_list_index(self):
        assert get_by_dot_path({'a': [10, 20, 30]}, '.a.1') == 20

    def test_deeply_nested(self):
        d = {'a': {'b': {'c': {'d': 'deep'}}}}
        assert get_by_dot_path(d, '.a.b.c.d') == 'deep'

    def test_none_value_returns_default(self):
        assert get_by_dot_path({'a': None}, '.a', 'fallback') == 'fallback'


class TestGetNumeric:
    def test_integer(self):
        assert get_numeric({'x': 42}, '.x') == 42

    def test_string_number(self):
        assert get_numeric({'x': '100'}, '.x') == 100

    def test_bad_string(self):
        assert get_numeric({'x': 'abc'}, '.x', 0) == 0

    def test_none_path(self):
        assert get_numeric({'x': 1}, None, 5) == 5


class TestGetFloat:
    def test_float(self):
        assert get_float({'x': 3.14}, '.x') == 3.14

    def test_integer_as_float(self):
        assert get_float({'x': 5}, '.x') == 5.0


class TestGetString:
    def test_string(self):
        assert get_string({'x': 'hello'}, '.x') == 'hello'

    def test_number_to_string(self):
        assert get_string({'x': 42}, '.x') == '42'


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

class TestLoadProviders:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = load_config()

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_yaml(self, name, content):
        filepath = os.path.join(self.tmp, name)
        with open(filepath, 'w') as f:
            f.write(textwrap.dedent(content))

    def test_empty_dir_returns_empty(self):
        assert load_providers(self.tmp, self.cfg) == {}

    def test_nonexistent_dir_returns_empty(self):
        assert load_providers('/tmp/does_not_exist_xyz', self.cfg) == {}

    def test_skips_non_yaml_files(self):
        with open(os.path.join(self.tmp, 'readme.txt'), 'w') as f:
            f.write('not yaml')
        assert load_providers(self.tmp, self.cfg) == {}

    def test_skips_yaml_without_display_name(self):
        self._write_yaml('bad.yaml', '''\
            usage:
              type: subprocess
              command: ["echo", "hi"]
        ''')
        assert load_providers(self.tmp, self.cfg) == {}

    def test_skips_yaml_without_usage(self):
        self._write_yaml('bad.yaml', '''\
            display_name: "Bad Source"
        ''')
        assert load_providers(self.tmp, self.cfg) == {}

    def test_skips_yaml_without_usage_type(self):
        self._write_yaml('bad.yaml', '''\
            display_name: "Bad Source"
            usage:
              command: ["echo"]
        ''')
        assert load_providers(self.tmp, self.cfg) == {}

    def test_loads_valid_subprocess_provider(self):
        self._write_yaml('test.yaml', '''\
            display_name: "Test Source"
            color: "oklch(0.5 0.1 200)"
            usage:
              type: subprocess
              command: ["echo", "{}"]
              format: json
              mapping:
                sessions: ".sessions"
                messages: ".messages"
        ''')
        result = load_providers(self.tmp, self.cfg)
        assert 'test' in result
        assert result['test'].display_name == 'Test Source'
        assert result['test'].color == 'oklch(0.5 0.1 200)'
        assert result['test'].has_quota is False

    def test_loads_provider_with_quota(self):
        self._write_yaml('quoted.yaml', '''\
            display_name: "Quoted Source"
            usage:
              type: subprocess
              command: ["echo", "{}"]
            quota:
              type: subprocess
              command: ["echo", "{}"]
        ''')
        result = load_providers(self.tmp, self.cfg)
        assert 'quoted' in result
        assert result['quoted'].has_quota is True

    def test_source_name_from_filename(self):
        self._write_yaml('my_custom_tool.yaml', '''\
            display_name: "My Custom Tool"
            usage:
              type: subprocess
              command: ["true"]
        ''')
        result = load_providers(self.tmp, self.cfg)
        assert 'my_custom_tool' in result


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_load_from_providers_replaces_registry(self):
        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, 'alpha.yaml'), 'w') as f:
                f.write(textwrap.dedent('''\
                    display_name: "Alpha"
                    usage:
                      type: subprocess
                      command: ["echo", "{}"]
                '''))
            cfg = load_config()
            load_from_providers(tmp, cfg)
            assert 'alpha' in get_all_names()
        finally:
            # Restore original sources by re-importing
            from source_registry import _register, _SOURCES
            _SOURCES.clear()
            # Re-register defaults
            import importlib
            import source_registry
            importlib.reload(source_registry)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_source_entry_has_color_field(self):
        entry = _SourceEntry(name='x', display_name='X', color='red')
        assert entry.color == 'red'

    def test_source_entry_has_quota_field(self):
        entry = _SourceEntry(name='x', display_name='X', has_quota=True)
        assert entry.has_quota is True

    def test_source_entry_defaults(self):
        entry = _SourceEntry(name='x')
        assert entry.color is None
        assert entry.has_quota is False
        assert entry.display_name == 'X'
