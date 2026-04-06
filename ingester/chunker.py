from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ingester.parser.base import ParsedDocument

_CODE_EXTENSIONS = {
    "py", "js", "ts", "go", "rs", "java", "c", "cpp", "rb", "php", "swift", "kt",
}

_BOUNDARY_PREFIXES = ("def ", "class ", "fn ", "func ", "async def ")

_TOKENS_PER_CHAR = 4  # 1 token ≈ 4 chars


@dataclass
class Chunk:
    text: str         # metadata header + content (embedded)
    raw_text: str     # content only (stored in SQLite)
    metadata: dict[str, Any]
    chunk_index: int


def _build_header(metadata: dict[str, Any]) -> str:
    source_path = metadata.get("path", "")
    filename = metadata.get("filename", os.path.basename(source_path))
    filetype = metadata.get("filetype", "")
    directory = os.path.dirname(source_path)
    mtime = metadata.get("mtime")
    if mtime is not None:
        modified = datetime.fromtimestamp(float(mtime), tz=UTC).strftime("%Y-%m-%d")
    else:
        modified = "unknown"

    lines = [
        f"File: {filename}",
        f"Type: {filetype}",
        f"Path: {directory}",
        f"Modified: {modified}",
    ]

    if "sheet" in metadata:
        lines.append(f"Sheet: {metadata['sheet']}")
    if "language" in metadata:
        lines.append(f"Language: {metadata['language']}")
    if "line_count" in metadata:
        lines.append(f"Lines: {metadata['line_count']}")

    return "\n".join(lines)


def _approx_tokens(text: str) -> int:
    return len(text) // _TOKENS_PER_CHAR


def _sliding_window_split(body: str, chunk_size: int, overlap: int) -> list[str]:
    chunk_chars = chunk_size * _TOKENS_PER_CHAR
    step_chars = (chunk_size - overlap) * _TOKENS_PER_CHAR
    if step_chars <= 0:
        step_chars = chunk_chars

    slices: list[str] = []
    start = 0
    while start < len(body):
        slices.append(body[start : start + chunk_chars])
        if start + chunk_chars >= len(body):
            break
        start += step_chars
    return slices


def _boundary_split(body: str, chunk_size: int, overlap: int) -> list[str] | None:
    lines = body.splitlines(keepends=True)
    boundary_indices: list[int] = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if any(stripped.startswith(p) for p in _BOUNDARY_PREFIXES):
            boundary_indices.append(i)

    if len(boundary_indices) < 2:
        return None

    # Build segments by joining lines between boundaries.
    # Include overlap_chars from the previous segment's tail.
    overlap_chars = overlap * _TOKENS_PER_CHAR
    segments: list[str] = []
    for seg_idx, start_line in enumerate(boundary_indices):
        next_idx = seg_idx + 1
        end_line = boundary_indices[next_idx] if next_idx < len(boundary_indices) else len(lines)
        segment_text = "".join(lines[start_line:end_line])
        if seg_idx > 0 and segments:
            tail = segments[-1][-overlap_chars:] if overlap_chars else ""
            segment_text = tail + segment_text
        segments.append(segment_text)
    return segments


class Chunker:
    def __init__(self, chunk_size: int = 512, overlap: int = 64) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        header = _build_header(doc.metadata)
        body = doc.text.strip()

        # Short-document fast path
        if _approx_tokens(body) <= 100:
            return [
                Chunk(
                    text=f"{header}\n\n{body}",
                    raw_text=body,
                    metadata=doc.metadata,
                    chunk_index=0,
                )
            ]

        # Code-aware splitting
        filetype = doc.metadata.get("filetype", "")
        is_code = filetype in _CODE_EXTENSIONS or "language" in doc.metadata
        raw_slices: list[str] | None = None
        if is_code:
            raw_slices = _boundary_split(body, self.chunk_size, self.overlap)

        if raw_slices is None:
            raw_slices = _sliding_window_split(body, self.chunk_size, self.overlap)

        return [
            Chunk(
                text=f"{header}\n\n{raw_text}",
                raw_text=raw_text,
                metadata=doc.metadata,
                chunk_index=idx,
            )
            for idx, raw_text in enumerate(raw_slices)
        ]
