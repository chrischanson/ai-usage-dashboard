from abc import ABC, abstractmethod
from typing import Any, Dict

class AdapterError(Exception):
    pass

class Adapter(ABC):
    @abstractmethod
    def fetch(self) -> Dict[str, Any]:
        """Fetch data from the source and return as a dictionary."""
        pass
