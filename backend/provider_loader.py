"""Provider loader — reads YAML provider definitions and builds registry entries.

Scans a directory for *.yaml files, validates each against the provider schema,
resolves the declared adapter type (subprocess, sqlite_query, http_json,
python_script) into callable parser factories and quota collector/normalizer
pairs, and returns a dict of source_name → _SourceEntry ready to populate the
source registry.

Security:
  - Uses yaml.safe_load() exclusively (never yaml.load with an arbitrary Loader).
  - python_script module paths are validated against traversal tokens.
  - subprocess adapters use list argv (no shell=True).
  - HTTP adapters enforce HTTPS (except localhost for testing).
  - SQLite adapters open in read-only mode.
"""

import os
import logging
from typing import Any, Callable, Dict, Optional

import yaml

from source_registry import _SourceEntry
from parsers.base import Parser, ParserResult, ModelUsage, SourceUnavailable
from adapters.subprocess_adapter import SubprocessAdapter
from adapters.sqlite_adapter import SqliteAdapter
from adapters.http_adapter import HttpAdapter
from adapters.script_adapter import (
    load_script_parser,
    load_script_quota_collector,
    load_script_quota_normalizer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dot-path field extraction
# ---------------------------------------------------------------------------

def get_by_dot_path(data: Any, path: str, default: Any = None) -> Any:
    """Extract a value from nested dicts/lists using a dot-notation path.

    Path must start with '.' (e.g. '.overview.sessions'). Returns *default*
    if any key in the chain is missing or the path is malformed.
    """
    if not path or not path.startswith('.'):
        return default
    keys = path.lstrip('.').split('.')
    current = data
    try:
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                current = current[int(key)]
            else:
                return default
            if current is None:
                return default
        return current
    except (KeyError, IndexError, ValueError, TypeError):
        return default


def get_numeric(data: Any, path: str, default: int = 0) -> int:
    """Extract an integer value via dot-path, falling back to *default*."""
    if not path:
        return default
    val = get_by_dot_path(data, path, default)
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def get_float(data: Any, path: str, default: float = 0.0) -> float:
    """Extract a float value via dot-path, falling back to *default*."""
    if not path:
        return default
    val = get_by_dot_path(data, path, default)
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def get_string(data: Any, path: str, default: str = "") -> str:
    """Extract a string value via dot-path, falling back to *default*."""
    if not path:
        return default
    val = get_by_dot_path(data, path, default)
    return str(val) if val is not None else default


# ---------------------------------------------------------------------------
# Generic parser (wraps non-python_script adapters)
# ---------------------------------------------------------------------------

class GenericParser(Parser):
    """A Parser implementation that delegates data fetching to an adapter and
    applies field mapping to produce a ParserResult."""

    def __init__(self, adapter: Any, mapping: Dict[str, str],
                 model_mapping: Optional[Dict[str, str]] = None,
                 models_path: str = ".models"):
        self.adapter = adapter
        self.mapping = mapping
        self.model_mapping = model_mapping
        self.models_path = models_path

    def parse(self) -> ParserResult:
        try:
            data = self.adapter.fetch()
        except Exception as e:
            raise SourceUnavailable(f"Adapter fetch failed: {e}")

        result = ParserResult()
        result.sessions = get_numeric(data, self.mapping.get("sessions"))
        result.messages = get_numeric(data, self.mapping.get("messages"))
        result.input_tokens = get_numeric(data, self.mapping.get("input_tokens"))
        result.output_tokens = get_numeric(data, self.mapping.get("output_tokens"))
        result.cache_read = get_numeric(data, self.mapping.get("cache_read"))
        result.cache_write = get_numeric(data, self.mapping.get("cache_write"))

        if self.model_mapping:
            models_list = get_by_dot_path(data, self.models_path, [])
            if isinstance(models_list, list):
                for item in models_list:
                    if not isinstance(item, dict):
                        continue
                    name_path = self.model_mapping.get('model_name', 'name')
                    model_name = item.get(name_path.lstrip('.'), '')
                    if not model_name:
                        continue
                    model = ModelUsage(model_name=model_name)
                    for field in ('messages', 'input_tokens', 'output_tokens',
                                  'cache_read', 'cache_write'):
                        field_key = self.model_mapping.get(field, field)
                        try:
                            setattr(model, field, int(item.get(field_key.lstrip('.'), 0) or 0))
                        except (ValueError, TypeError):
                            pass
                    cost_key = self.model_mapping.get('cost', 'cost')
                    try:
                        model.cost = float(item.get(cost_key.lstrip('.'), 0.0) or 0.0)
                    except (ValueError, TypeError):
                        pass
                    result.models.append(model)

        return result


# ---------------------------------------------------------------------------
# Adapter construction
# ---------------------------------------------------------------------------

def _create_adapter(config: Dict[str, Any], cfg_obj: Any) -> Any:
    """Create an adapter instance from a usage/quota config block."""
    type_ = config.get("type")
    if type_ == "subprocess":
        return SubprocessAdapter(
            command=config.get("command", []),
            format=config.get("format", "json"),
            preprocessor=config.get("preprocessor"),
            timeout=getattr(cfg_obj, "subprocess_timeout", 30),
        )
    elif type_ == "sqlite_query":
        return SqliteAdapter(
            db_path=config.get("db_path", ""),
            overview_query=config.get("overview_query", ""),
            models_query=config.get("models_query"),
        )
    elif type_ == "http_json":
        return HttpAdapter(
            url=config.get("url", ""),
            headers=config.get("headers", {}),
            timeout=getattr(cfg_obj, "network_timeout", 10),
        )
    else:
        raise ValueError(f"Unknown adapter type: {type_}")


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

def _build_parser_factory(usage_config: Dict[str, Any], cfg_obj: Any) -> Callable:
    """Build a zero-arg callable that returns a Parser instance."""
    type_ = usage_config.get("type")

    if type_ == "python_script":
        module_path = usage_config.get("module")
        if not module_path:
            raise ValueError("python_script usage requires 'module' path")
        create_fn = load_script_parser(module_path)

        def parser_factory():
            return create_fn()
        return parser_factory
    else:
        mapping = usage_config.get("mapping", {})
        model_mapping = usage_config.get("model_mapping")
        models_path = usage_config.get("models_path", ".models")

        def parser_factory():
            adapter = _create_adapter(usage_config, cfg_obj)
            return GenericParser(adapter, mapping, model_mapping, models_path)
        return parser_factory


def _build_quota_collector(quota_config: Dict[str, Any], cfg_obj: Any) -> Callable:
    """Build a zero-arg callable that fetches raw quota data."""
    type_ = quota_config.get("type")

    if type_ == "python_script":
        module_path = quota_config.get("module")
        if not module_path:
            raise ValueError("python_script quota requires 'module' path")
        return load_script_quota_collector(module_path)
    else:
        def collector():
            adapter = _create_adapter(quota_config, cfg_obj)
            try:
                return adapter.fetch()
            except Exception as e:
                return {"error": str(e)}
        return collector


def _build_quota_normalizer(quota_config: Dict[str, Any]) -> Callable:
    """Build a callable that normalizes raw quota data."""
    type_ = quota_config.get("type")

    if type_ == "python_script":
        module_path = quota_config.get("module")
        if not module_path:
            raise ValueError("python_script quota requires 'module' path")
        return load_script_quota_normalizer(module_path)
    else:
        # For non-script adapters, the normalizer is specified as a module.function path
        normalizer_path = quota_config.get("normalizer")
        if normalizer_path:
            if ".." in normalizer_path:
                raise ValueError("Invalid normalizer module path")
            try:
                import importlib
                module_name, func_name = normalizer_path.rsplit(".", 1)
                module = importlib.import_module(module_name)
                return getattr(module, func_name)
            except Exception as e:
                raise ValueError(f"Failed to load normalizer {normalizer_path}: {e}")
        # Default: pass-through
        return lambda raw: raw


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_providers(providers_dir: str, cfg: Any) -> Dict[str, _SourceEntry]:
    """Scan *providers_dir* for *.yaml files and return a dict of
    source_name → _SourceEntry, ready to populate the registry.

    Fails gracefully per-file: a malformed YAML file is logged and skipped,
    never crashes the loader.
    """
    providers: Dict[str, _SourceEntry] = {}

    if not os.path.isdir(providers_dir):
        return providers

    for filename in sorted(os.listdir(providers_dir)):
        if not filename.endswith((".yaml", ".yml")):
            continue

        filepath = os.path.join(providers_dir, filename)
        if not os.path.isfile(filepath):
            continue

        source_name = os.path.splitext(filename)[0]

        try:
            with open(filepath, 'r') as f:
                # Security: yaml.safe_load only — never yaml.load
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                logger.warning("Skipping %s: not a YAML dictionary", filename)
                continue

            display_name = data.get("display_name")
            if not display_name:
                logger.warning("Skipping %s: missing display_name", filename)
                continue

            usage_config = data.get("usage")
            if not usage_config or not isinstance(usage_config, dict):
                logger.warning("Skipping %s: missing or invalid usage config", filename)
                continue

            if not usage_config.get("type"):
                logger.warning("Skipping %s: missing usage.type", filename)
                continue

            color = data.get("color")

            # Build parser factory
            parser_factory = _build_parser_factory(usage_config, cfg)

            # Build quota (optional)
            quota_config = data.get("quota")
            quota_collector = None
            quota_normalizer = None
            has_quota = False

            if quota_config and isinstance(quota_config, dict) and quota_config.get("type"):
                quota_collector = _build_quota_collector(quota_config, cfg)
                quota_normalizer = _build_quota_normalizer(quota_config)
                has_quota = True

            entry = _SourceEntry(
                name=source_name,
                parser=parser_factory,
                quota_collector=quota_collector,
                quota_normalizer=quota_normalizer,
                display_name=display_name,
                color=color,
                has_quota=has_quota,
            )
            providers[source_name] = entry
            logger.info("Loaded provider: %s (%s)", source_name, display_name)

        except Exception as e:
            logger.error("Failed to load provider from %s: %s", filename, e)

    return providers
