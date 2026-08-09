import os
import re
from urllib.parse import urlparse
import httpx
from typing import Any, Dict, Optional
from adapters.base import Adapter, AdapterError

class HttpAdapter(Adapter):
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        
        # Validate URL scheme
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https":
            if parsed_url.hostname not in ("localhost", "127.0.0.1"):
                raise ValueError("HTTP adapter requires HTTPS URL, or localhost for testing")

    def _interpolate_headers(self) -> Dict[str, str]:
        interpolated = {}
        env_var_pattern = re.compile(r'\$\{([^}]+)\}')
        
        for k, v in self.headers.items():
            def replace_env(match):
                var_name = match.group(1)
                return os.environ.get(var_name, '')
            interpolated[k] = env_var_pattern.sub(replace_env, v)
        return interpolated

    def fetch(self) -> Dict[str, Any]:
        headers = self._interpolate_headers()
        
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self.url, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            raise AdapterError(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise AdapterError(f"Request failed: {e}")
        except Exception as e:
            raise AdapterError(f"HTTP adapter error: {e}")
