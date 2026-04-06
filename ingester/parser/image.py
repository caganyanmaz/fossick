from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from ingester.parser.base import BaseParser, ParsedDocument

_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "tiff", "bmp"}


class ImageParser(BaseParser):
    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lstrip(".").lower() in _EXTENSIONS

    def parse(self, path: str) -> ParsedDocument:
        p = Path(path)
        filetype = p.suffix.lstrip(".").lower()
        stat = p.stat()

        width: int = 0
        height: int = 0
        mode: str = ""
        text: str = ""

        # Get image dimensions via Pillow
        try:
            from PIL import Image

            with Image.open(str(p)) as img:
                width, height = img.size
                mode = img.mode
        except Exception as exc:
            logger.warning("Pillow failed to open {}: {}", path, exc)

        # Attempt OCR via Docling
        try:
            from docling.document_converter import DocumentConverter

            result = DocumentConverter().convert(str(p))
            ocr_text = result.document.export_to_markdown()
            if ocr_text and ocr_text.strip():
                text = ocr_text
            else:
                logger.warning("Docling OCR produced no text for {}", path)
        except Exception as exc:
            logger.warning("Docling OCR failed for {}: {}. Returning metadata only.", path, exc)

        meta: dict[str, Any] = {
            "filename": p.name,
            "path": str(p),
            "filetype": filetype,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "width": width,
            "height": height,
            "mode": mode,
        }
        return ParsedDocument(text=text, metadata=meta, source_path=str(p))
