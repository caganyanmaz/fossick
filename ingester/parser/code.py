from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from ingester.parser.base import BaseParser, ParsedDocument

_DOCSTRING_MARKERS = ('"""', "'''", "/**", "/*")


class CodeParser(BaseParser):
    def can_parse(self, path: str) -> bool:
        try:
            get_lexer_for_filename(path)
            return True
        except ClassNotFound:
            return False

    def parse(self, path: str) -> ParsedDocument:
        p = Path(path)
        filetype = p.suffix.lstrip(".").lower()
        stat = p.stat()

        try:
            lexer = get_lexer_for_filename(str(p))
            language = lexer.name
        except ClassNotFound:
            language = "text"

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Could not read code file {}: {}", path, exc)
            text = ""

        lines = text.splitlines()
        first_50 = lines[:50]
        has_docstring = any(marker in line for line in first_50 for marker in _DOCSTRING_MARKERS)

        meta: dict[str, Any] = {
            "filename": p.name,
            "path": str(p),
            "filetype": filetype,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "language": language,
            "line_count": len(lines),
            "has_docstring": has_docstring,
        }
        return ParsedDocument(text=text, metadata=meta, source_path=str(p))
