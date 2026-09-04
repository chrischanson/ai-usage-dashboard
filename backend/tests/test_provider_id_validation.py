"""Tests for provider/source id slug validation in provider_loader.

Source ids are derived from YAML filename stems and flow verbatim into
generated CSS (class names, custom property names) and DOM attributes on
the frontend (see frontend/js/sources.js). A stray character in a filename
must not be able to corrupt a stylesheet, so ids are restricted to
`^[a-z0-9_-]+$` at load time. One bad provider file must not take down the
rest of the dashboard -- it should be skipped with a logged warning while
all valid providers still load.
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from provider_loader import load_providers, _VALID_ID_RE
from config import load_config


GOOD_YAML = """
display_name: "Weird"
color: "oklch(0.5 0.1 0)"
usage:
  type: python_script
  module: "providers.scripts.codex_usage"
"""


class TestValidIdRegex:
    def test_accepts_lowercase_letters_digits_underscore_hyphen(self):
        for name in ('agy', 'claude', 'codex', 'opencode', 'my_source-2'):
            assert _VALID_ID_RE.match(name), name

    def test_rejects_uppercase(self):
        assert not _VALID_ID_RE.match('Claude')

    def test_rejects_spaces(self):
        assert not _VALID_ID_RE.match('bad name')

    def test_rejects_dots(self):
        assert not _VALID_ID_RE.match('has.dot')

    def test_rejects_path_traversal_like_tokens(self):
        assert not _VALID_ID_RE.match('..evil')

    def test_rejects_special_characters(self):
        for name in ('bad!', 'a/b', 'a<b>', 'a"b', "a'b"):
            assert not _VALID_ID_RE.match(name), name


class TestLoadProvidersIdValidation:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = load_config()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, filename):
        path = os.path.join(self.tmpdir, filename)
        with open(path, 'w') as f:
            f.write(GOOD_YAML)
        return path

    def test_real_providers_all_load(self):
        providers_dir = os.path.join(os.path.dirname(__file__), '..', 'providers')
        providers = load_providers(providers_dir, self.cfg)
        assert set(providers.keys()) == {'agy', 'claude', 'codex', 'opencode'}

    def test_valid_id_loads(self):
        self._write('my_valid-source.yaml')
        providers = load_providers(self.tmpdir, self.cfg)
        assert 'my_valid-source' in providers

    def test_uppercase_id_is_skipped(self):
        self._write('BadName.yaml')
        providers = load_providers(self.tmpdir, self.cfg)
        assert providers == {}

    def test_id_with_space_is_skipped(self):
        self._write('bad name.yaml')
        providers = load_providers(self.tmpdir, self.cfg)
        assert providers == {}

    def test_id_with_dot_is_skipped(self):
        self._write('has.dot.yaml')
        providers = load_providers(self.tmpdir, self.cfg)
        assert providers == {}

    def test_one_bad_provider_does_not_block_others(self):
        self._write('BadName.yaml')
        self._write('good_one.yaml')
        providers = load_providers(self.tmpdir, self.cfg)
        assert set(providers.keys()) == {'good_one'}

    def test_bad_id_logs_warning_naming_file_and_id(self, caplog):
        import logging
        self._write('Bad Name!.yaml')
        with caplog.at_level(logging.WARNING, logger='provider_loader'):
            load_providers(self.tmpdir, self.cfg)
        assert any(
            'Bad Name!.yaml' in rec.getMessage() and 'Bad Name!' in rec.getMessage()
            for rec in caplog.records
        )
