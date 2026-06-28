from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


class SourceUnavailable(Exception):
    """Raised when a source's files/command are missing or unparseable."""
    pass


@dataclass
class ModelUsage:
    model_name: str
    messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0


@dataclass
class ParserResult:
    sessions: int = 0
    messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    models: List[ModelUsage] = field(default_factory=list)


class Parser(ABC):
    @abstractmethod
    def parse(self) -> ParserResult:
        """Parse the data source and return usage data.
        Raises SourceUnavailable if the source is not available."""
