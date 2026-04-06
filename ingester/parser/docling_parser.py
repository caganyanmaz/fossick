from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from ingester.parser.base import BaseParser, ParsedDocument

_EXTENSIONS = {"pdf", "docx", "pptx", "html", "htm", "md", "xml"}


class DoclingParser(BaseParser):
    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lstrip(".").lower() in _EXTENSIONS

    def parse(self, path: str) -> ParsedDocument:
        p = Path(path)
        filetype = p.suffix.lstrip(".").lower()
        stat = p.stat()
        base_meta: dict[str, Any] = {
            "filename": p.name,
            "path": str(p),
            "filetype": filetype,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "title": "",
            "author": "",
        }

        try:
            from docling.document_converter import DocumentConverter

            result = DocumentConverter().convert(str(p))
            doc = result.document
            text = doc.export_to_markdown()

            # Best-effort metadata extraction
            meta = getattr(doc, "metadata", None) or {}
            if isinstance(meta, dict):
                base_meta["title"] = meta.get("title", "")
                base_meta["author"] = meta.get("author", "")
            else:
                try:
                    base_meta["title"] = getattr(meta, "title", "") or ""
                    base_meta["author"] = getattr(meta, "author", "") or ""
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("Docling failed for {}: {}. Falling back to plain text.", path, exc)
            text = p.read_text(errors="replace")

        return ParsedDocument(text=text, metadata=base_meta, source_path=str(p))
