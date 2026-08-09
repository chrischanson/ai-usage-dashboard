import importlib
from typing import Any, Callable

def load_script_parser(module_path: str) -> Callable[..., Any]:
    if not module_path or module_path.startswith(".") or ".." in module_path:
        raise ValueError("Invalid module path")
    try:
        module = importlib.import_module(module_path)
        if not hasattr(module, "create_parser"):
            raise ValueError(f"Module {module_path} missing create_parser()")
        return getattr(module, "create_parser")
    except Exception as e:
        raise RuntimeError(f"Failed to load script parser from {module_path}: {e}")

def load_script_quota_collector(module_path: str) -> Callable[..., Any]:
    if not module_path or module_path.startswith(".") or ".." in module_path:
        raise ValueError("Invalid module path")
    try:
        module = importlib.import_module(module_path)
        if not hasattr(module, "collect"):
            raise ValueError(f"Module {module_path} missing collect()")
        return getattr(module, "collect")
    except Exception as e:
        raise RuntimeError(f"Failed to load script quota collector from {module_path}: {e}")

def load_script_quota_normalizer(module_path: str) -> Callable[..., Any]:
    if not module_path or module_path.startswith(".") or ".." in module_path:
        raise ValueError("Invalid module path")
    try:
        module = importlib.import_module(module_path)
        if not hasattr(module, "normalize"):
            raise ValueError(f"Module {module_path} missing normalize()")
        return getattr(module, "normalize")
    except Exception as e:
        raise RuntimeError(f"Failed to load script quota normalizer from {module_path}: {e}")
