import os
import json
import sqlite3
import tempfile
import pytest
from unittest import mock
import httpx
import subprocess

from adapters.base import AdapterError
from adapters.subprocess_adapter import SubprocessAdapter
from adapters.http_adapter import HttpAdapter
from adapters.sqlite_adapter import SqliteAdapter
from provider_loader import GenericParser, _build_parser_factory, _create_adapter
from parsers.base import SourceUnavailable


# --- 1. GenericParser Tests ---

class DummyAdapter:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error

    def fetch(self):
        if self.error:
            raise self.error
        return self.data

class TestGenericParser:
    def test_generic_parser_maps_dot_path_fields(self):
        data = {
            "stats": {
                "sess": 10,
                "msgs": 20,
                "in_tok": 100,
                "out_tok": 200,
                "c_read": 50,
                "c_write": 60
            }
        }
        mapping = {
            "sessions": ".stats.sess",
            "messages": ".stats.msgs",
            "input_tokens": ".stats.in_tok",
            "output_tokens": ".stats.out_tok",
            "cache_read": ".stats.c_read",
            "cache_write": ".stats.c_write"
        }
        parser = GenericParser(DummyAdapter(data), mapping)
        result = parser.parse()
        assert result.sessions == 10
        assert result.messages == 20
        assert result.input_tokens == 100
        assert result.output_tokens == 200
        assert result.cache_read == 50
        assert result.cache_write == 60

    def test_generic_parser_model_extraction(self):
        data = {
            "my_models": [
                {"name": "model_a", "msgs": 5, "cost": 0.5},
                {"name": "model_b", "msgs": 15, "cost": 1.5}
            ]
        }
        mapping = {}
        model_mapping = {
            "model_name": ".name",
            "messages": ".msgs",
            "cost": ".cost"
        }
        parser = GenericParser(DummyAdapter(data), mapping, model_mapping, ".my_models")
        result = parser.parse()
        assert len(result.models) == 2
        assert result.models[0].model_name == "model_a"
        assert result.models[0].messages == 5
        assert result.models[0].cost == 0.5
        assert result.models[1].model_name == "model_b"
        assert result.models[1].messages == 15
        assert result.models[1].cost == 1.5

    def test_generic_parser_missing_fields_default_to_zero(self):
        data = {"stats": {}}
        mapping = {"sessions": ".stats.sess"}
        parser = GenericParser(DummyAdapter(data), mapping)
        result = parser.parse()
        assert result.sessions == 0

    def test_generic_parser_empty_models_list(self):
        data = {"my_models": []}
        parser = GenericParser(DummyAdapter(data), {}, {}, ".my_models")
        result = parser.parse()
        assert result.models == []

    def test_generic_parser_invalid_adapter_output(self):
        # Output is not a dict
        data = ["not", "a", "dict"]
        mapping = {"sessions": ".stats.sess"}
        parser = GenericParser(DummyAdapter(data), mapping)
        result = parser.parse()
        assert result.sessions == 0

    def test_generic_parser_raises_source_unavailable_on_adapter_error(self):
        parser = GenericParser(DummyAdapter(error=Exception("Fetch failed")), {})
        with pytest.raises(SourceUnavailable):
            parser.parse()

# --- 2. SubprocessAdapter Tests ---

class TestSubprocessAdapter:
    @mock.patch("subprocess.run")
    def test_successful_json_command_output(self, mock_run):
        mock_run.return_value.stdout = '{"key": "value"}'
        mock_run.return_value.check_returncode.return_value = None
        adapter = SubprocessAdapter(["echo", "hi"])
        assert adapter.fetch() == {"key": "value"}

    @mock.patch("subprocess.run")
    def test_command_timeout_raises_adapter_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["echo"], timeout=30)
        adapter = SubprocessAdapter(["echo", "hi"])
        with pytest.raises(AdapterError, match="timed out"):
            adapter.fetch()

    @mock.patch("subprocess.run")
    def test_non_zero_exit_code_raises_adapter_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["echo"], stderr="error")
        adapter = SubprocessAdapter(["echo", "hi"])
        with pytest.raises(AdapterError, match="failed with exit code 1"):
            adapter.fetch()

    @mock.patch("subprocess.run")
    def test_invalid_json_output_raises_adapter_error(self, mock_run):
        mock_run.return_value.stdout = 'invalid json'
        mock_run.return_value.check_returncode.return_value = None
        adapter = SubprocessAdapter(["echo", "hi"])
        with pytest.raises(AdapterError, match="Failed to parse JSON"):
            adapter.fetch()

    @mock.patch("subprocess.run")
    def test_text_format_with_preprocessor(self, mock_run):
        # Create a dummy preprocessor in a temporary module or just mock importlib
        mock_run.return_value.stdout = 'text output'
        mock_run.return_value.check_returncode.return_value = None
        
        with mock.patch("importlib.import_module") as mock_import:
            mock_module = mock.MagicMock()
            mock_module.parse_func = lambda x: {"parsed": x}
            mock_import.return_value = mock_module
            
            adapter = SubprocessAdapter(["echo"], format="text", preprocessor="dummy.module.parse_func")
            assert adapter.fetch() == {"parsed": "text output"}

    def test_text_format_without_preprocessor_raises_error(self):
        adapter = SubprocessAdapter(["echo"], format="text")
        with pytest.raises(AdapterError, match="requires a preprocessor"):
            adapter.fetch()

    def test_preprocessor_path_traversal_raises_error(self):
        adapter = SubprocessAdapter(["echo"], format="text", preprocessor="../malicious.func")
        with pytest.raises(AdapterError, match="Invalid preprocessor module path"):
            adapter.fetch()

# --- 3. HttpAdapter Tests ---

class TestHttpAdapter:
    def test_https_url_accepted(self):
        adapter = HttpAdapter("https://example.com/api")
        assert adapter.url == "https://example.com/api"

    def test_http_localhost_accepted(self):
        adapter = HttpAdapter("http://localhost:8080/api")
        assert adapter.url == "http://localhost:8080/api"

    def test_http_non_localhost_raises_value_error(self):
        with pytest.raises(ValueError, match="requires HTTPS"):
            HttpAdapter("http://example.com/api")

    @mock.patch.dict(os.environ, {"API_KEY": "secret123"})
    @mock.patch("httpx.Client.get")
    def test_header_env_var_interpolation(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_get.return_value = mock_response
        
        adapter = HttpAdapter("https://example.com", headers={"Authorization": "Bearer ${API_KEY}"})
        adapter.fetch()
        
        mock_get.assert_called_once_with("https://example.com", headers={"Authorization": "Bearer secret123"})

    @mock.patch("httpx.Client.get")
    def test_successful_fetch_returns_json_dict(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"key": "val"}
        mock_get.return_value = mock_response
        
        adapter = HttpAdapter("https://example.com")
        assert adapter.fetch() == {"key": "val"}

    @mock.patch("httpx.Client.get")
    def test_http_error_raises_adapter_error(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=mock.MagicMock(), response=mock_response)
        mock_get.return_value = mock_response
        
        adapter = HttpAdapter("https://example.com")
        with pytest.raises(AdapterError, match="HTTP error 404"):
            adapter.fetch()

    @mock.patch("httpx.Client.get")
    def test_connection_error_raises_adapter_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("Connection failed")
        adapter = HttpAdapter("https://example.com")
        with pytest.raises(AdapterError, match="Request failed"):
            adapter.fetch()

# --- 4. SqliteAdapter Tests ---

class TestSqliteAdapter:
    def setup_method(self):
        self.tmp_fd, self.db_path = tempfile.mkstemp()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("CREATE TABLE overview (sessions INT, messages INT)")
        self.conn.execute("INSERT INTO overview VALUES (10, 20)")
        self.conn.execute("CREATE TABLE models (name TEXT, msgs INT)")
        self.conn.execute("INSERT INTO models VALUES ('model_a', 5)")
        self.conn.execute("INSERT INTO models VALUES ('model_b', 15)")
        self.conn.commit()
        self.conn.close()

    def teardown_method(self):
        os.close(self.tmp_fd)
        os.remove(self.db_path)

    def test_successful_query_with_overview_and_models(self):
        adapter = SqliteAdapter(
            self.db_path,
            overview_query="SELECT * FROM overview",
            models_query="SELECT * FROM models"
        )
        result = adapter.fetch()
        assert result["overview"]["sessions"] == 10
        assert result["overview"]["messages"] == 20
        assert len(result["models"]) == 2
        assert result["models"][0]["name"] == "model_a"
        assert result["models"][0]["msgs"] == 5

    def test_overview_only(self):
        adapter = SqliteAdapter(
            self.db_path,
            overview_query="SELECT * FROM overview"
        )
        result = adapter.fetch()
        assert result["overview"]["sessions"] == 10
        assert "models" in result
        assert len(result["models"]) == 0

    def test_path_traversal_in_db_path_raises_value_error(self):
        with pytest.raises(ValueError, match="Path traversal not allowed"):
            SqliteAdapter("../malicious.db", "SELECT 1")

    def test_sqlite_error_raises_adapter_error(self):
        adapter = SqliteAdapter(
            self.db_path,
            overview_query="SELECT * FROM nonexistent_table"
        )
        with pytest.raises(AdapterError, match="SQLite error"):
            adapter.fetch()

# --- 5. Integration Test ---

class TestIntegration:
    @mock.patch("adapters.http_adapter.HttpAdapter.fetch")
    def test_full_yaml_to_parser_result_flow(self, mock_fetch):
        # Mock adapter to return some data
        mock_fetch.return_value = {
            "data": {
                "totals": {"sess": 100},
                "model_usage": [
                    {"model_id": "gpt-4", "in": 50, "out": 100}
                ]
            }
        }
        
        usage_config = {
            "type": "http_json",
            "url": "https://api.example.com/usage",
            "mapping": {
                "sessions": ".data.totals.sess"
            },
            "models_path": ".data.model_usage",
            "model_mapping": {
                "model_name": ".model_id",
                "input_tokens": ".in",
                "output_tokens": ".out"
            }
        }
        
        # We need a dummy cfg object
        class DummyCfg:
            network_timeout = 10
            
        parser_factory = _build_parser_factory(usage_config, DummyCfg())
        parser = parser_factory()
        
        result = parser.parse()
        
        assert result.sessions == 100
        assert len(result.models) == 1
        assert result.models[0].model_name == "gpt-4"
        assert result.models[0].input_tokens == 50
        assert result.models[0].output_tokens == 100
