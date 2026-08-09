import json
import shlex
import subprocess
import importlib
from typing import Any, Dict, List, Optional
from adapters.base import Adapter, AdapterError

class SubprocessAdapter(Adapter):
    def __init__(self, command: List[str], format: str = "json", preprocessor: Optional[str] = None, timeout: int = 30):
        self.command = command
        self.format = format
        self.preprocessor = preprocessor
        self.timeout = timeout

    def fetch(self) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                self.command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False
            )
            result.check_returncode()
        except subprocess.TimeoutExpired:
            raise AdapterError(f"Command timed out after {self.timeout} seconds")
        except subprocess.CalledProcessError as e:
            raise AdapterError(f"Command failed with exit code {e.returncode}: {e.stderr}")
        except Exception as e:
            raise AdapterError(f"Failed to execute command: {e}")

        output = result.stdout

        if self.format == "json":
            try:
                return json.loads(output)
            except json.JSONDecodeError as e:
                raise AdapterError(f"Failed to parse JSON output: {e}")
        elif self.format == "text":
            if not self.preprocessor:
                raise AdapterError("Text format requires a preprocessor")
            
            if ".." in self.preprocessor or self.preprocessor.startswith("."):
                raise AdapterError("Invalid preprocessor module path")
                
            try:
                module_name, func_name = self.preprocessor.rsplit(".", 1)
                module = importlib.import_module(module_name)
                func = getattr(module, func_name)
            except Exception as e:
                raise AdapterError(f"Failed to load preprocessor {self.preprocessor}: {e}")
            
            try:
                parsed = func(output)
                if not isinstance(parsed, dict):
                    raise AdapterError("Preprocessor must return a dictionary")
                return parsed
            except Exception as e:
                raise AdapterError(f"Preprocessor error: {e}")
        else:
            raise AdapterError(f"Unsupported format: {self.format}")
