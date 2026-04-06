from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedDocument:
    text: str
    metadata: dict[str, Any]
    source_path: str


class BaseParser(ABC):
    @abstractmethod
    def can_parse(self, path: str) -> bool: ...

    @abstractmethod
    def parse(self, path: str) -> ParsedDocument: ...
