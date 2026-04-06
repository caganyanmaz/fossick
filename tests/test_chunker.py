"""Tests for ingester/chunker.py."""

from __future__ import annotations

import time

from ingester.chunker import Chunk, Chunker
from ingester.parser.base import ParsedDocument

_BASE_META = {
    "filename": "test.txt",
    "path": "/tmp/test.txt",
    "filetype": "txt",
    "mtime": time.time(),
}


def _make_doc(text: str, meta: dict | None = None) -> ParsedDocument:
    return ParsedDocument(
        text=text,
        metadata=meta or _BASE_META,
        source_path="/tmp/test.txt",
    )


def _long_body(tokens: int = 600) -> str:
    # Each word is ~5 chars + space = 6 chars ≈ 1.5 tokens; easier to just pad.
    return "word " * (tokens * 4 // 5)


def test_single_chunk_short_doc() -> None:
    chunker = Chunker(chunk_size=512, overlap=64)
    doc = _make_doc("Short text.")
    chunks = chunker.chunk(doc)
    assert len(chunks) == 1
    assert isinstance(chunks[0], Chunk)
    assert chunks[0].chunk_index == 0


def test_multiple_chunks_long_doc() -> None:
    chunker = Chunker(chunk_size=512, overlap=64)
    body = _long_body(tokens=1500)
    doc = _make_doc(body)
    chunks = chunker.chunk(doc)
    assert len(chunks) > 1


def test_overlap_content() -> None:
    chunker = Chunker(chunk_size=100, overlap=20)
    body = _long_body(tokens=400)
    doc = _make_doc(body)
    chunks = chunker.chunk(doc)
    assert len(chunks) >= 2
    # The tail of chunk 0's raw_text should appear at the start of chunk 1's raw_text.
    overlap_chars = 20 * 4
    tail = chunks[0].raw_text[-overlap_chars:]
    assert chunks[1].raw_text.startswith(tail), (
        "Expected overlap content from chunk 0 to appear at the start of chunk 1"
    )


def test_metadata_header_in_every_chunk() -> None:
    chunker = Chunker(chunk_size=100, overlap=20)
    body = _long_body(tokens=400)
    doc = _make_doc(body)
    chunks = chunker.chunk(doc)
    for chunk in chunks:
        assert "File:" in chunk.text
        assert "Type:" in chunk.text


def test_code_boundary_splitting() -> None:
    chunker = Chunker(chunk_size=512, overlap=64)
    body = "\n".join(
        [
            "def alpha():",
            "    return 1",
            "",
            "def beta():",
            "    return 2",
            "",
            "def gamma():",
            "    return 3",
            "",
            "def delta():",
            "    return 4",
        ]
    )
    meta = {**_BASE_META, "filetype": "py"}
    doc = _make_doc(body, meta=meta)
    chunks = chunker.chunk(doc)
    # Each chunk's raw_text should start at a function boundary (after optional overlap tail).
    # At minimum, every chunk must contain a "def " line.
    for chunk in chunks:
        assert "def " in chunk.raw_text, f"Expected 'def ' in chunk raw_text: {chunk.raw_text!r}"


def test_chunk_index_sequential() -> None:
    chunker = Chunker(chunk_size=100, overlap=20)
    body = _long_body(tokens=600)
    doc = _make_doc(body)
    chunks = chunker.chunk(doc)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
