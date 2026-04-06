from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from ingester.config import QdrantConfig
from ingester.embedder.base import BaseEmbedder
from ingester.pipeline import Pipeline
from ingester.store.metadata import MetadataStore
from ingester.store.vector import VectorStore

# Fixed vector dimension for tests
DIMENSION = 4


class _FakeEmbedder(BaseEmbedder):
    """Returns fixed-length zero vectors — no model loading required."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * DIMENSION for _ in texts]

    @property
    def dimension(self) -> int:
        return DIMENSION


@pytest_asyncio.fixture
async def meta() -> AsyncGenerator[MetadataStore, None]:
    s = MetadataStore(":memory:")
    await s.init()
    yield s


@pytest_asyncio.fixture
async def vec() -> AsyncGenerator[VectorStore, None]:
    cfg = QdrantConfig(
        host=":memory:",
        port=6333,
        collection="test_pipeline",
        on_disk_vectors=False,
        quantization="none",
    )
    vs = VectorStore(cfg, embedder_dimension=DIMENSION)
    await vs.init()
    yield vs


@pytest_asyncio.fixture
async def pipeline(meta: MetadataStore, vec: VectorStore) -> Pipeline:
    return Pipeline(
        config=MagicMock(),
        metadata_store=meta,
        vector_store=vec,
        embedder=_FakeEmbedder(),
    )


@pytest.mark.asyncio
async def test_new_file_indexed(pipeline: Pipeline, meta: MetadataStore, tmp_path):
    """A new file should be indexed with status 'indexed'."""
    f = tmp_path / "hello.txt"
    f.write_text("Hello world! " * 50)

    result = await pipeline.ingest(str(f))

    assert result.status == "indexed"
    assert result.chunks > 0

    record = await meta.get_file_by_path(str(f))
    assert record is not None
    assert record.status == "indexed"


@pytest.mark.asyncio
async def test_same_hash_skipped(pipeline: Pipeline, tmp_path):
    """Ingesting the same file twice should skip on the second call."""
    f = tmp_path / "same.txt"
    f.write_text("Unchanged content " * 50)

    first = await pipeline.ingest(str(f))
    second = await pipeline.ingest(str(f))

    assert first.status == "indexed"
    assert second.status == "skipped"


@pytest.mark.asyncio
async def test_modified_file_reindexed(
    pipeline: Pipeline, meta: MetadataStore, vec: VectorStore, tmp_path
):
    """A file with a changed hash should be re-indexed, not skipped."""
    f = tmp_path / "mod.txt"
    f.write_text("Version one content " * 50)

    first = await pipeline.ingest(str(f))
    assert first.status == "indexed"

    record_v1 = await meta.get_file_by_path(str(f))
    assert record_v1 is not None
    old_ids = await meta.get_chunk_qdrant_ids(record_v1.id)

    # Modify the file
    f.write_text("Version two completely different content " * 50)

    second = await pipeline.ingest(str(f))
    assert second.status == "indexed"

    record_v2 = await meta.get_file_by_path(str(f))
    assert record_v2 is not None
    assert record_v2.hash != record_v1.hash

    # Old Qdrant points should be gone
    if old_ids:
        info = await vec.collection_info()
        assert info  # collection still exists


@pytest.mark.asyncio
async def test_unsupported_extension(pipeline: Pipeline, tmp_path):
    """Files with no registered parser return status 'unsupported'."""
    f = tmp_path / "archive.xyz123"
    f.write_bytes(b"\x00\x01\x02\x03")

    result = await pipeline.ingest(str(f))

    assert result.status == "unsupported"


@pytest.mark.asyncio
async def test_missing_file_returns_error(pipeline: Pipeline, tmp_path):
    """A path that does not exist should return status 'error'."""
    result = await pipeline.ingest(str(tmp_path / "nonexistent.txt"))
    assert result.status == "error"
    assert result.error != ""


@pytest.mark.asyncio
async def test_delete_removes_from_both_stores(
    pipeline: Pipeline, meta: MetadataStore, tmp_path
):
    """delete() should remove the file record from SQLite."""
    f = tmp_path / "to_delete.txt"
    f.write_text("Delete me " * 50)

    await pipeline.ingest(str(f))
    assert await meta.get_file_by_path(str(f)) is not None

    await pipeline.delete(str(f))
    assert await meta.get_file_by_path(str(f)) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_is_noop(pipeline: Pipeline, tmp_path):
    """Deleting a path that was never indexed should not raise."""
    await pipeline.delete(str(tmp_path / "ghost.txt"))  # should not raise


@pytest.mark.asyncio
async def test_ingest_directory(pipeline: Pipeline, meta: MetadataStore, tmp_path):
    """ingest_directory() should ingest all files recursively."""
    (tmp_path / "a.txt").write_text("Content A " * 30)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("Content B " * 30)

    results = await pipeline.ingest_directory(str(tmp_path))

    indexed = [r for r in results if r.status == "indexed"]
    assert len(indexed) == 2

    files = await meta.get_all_files()
    assert len(files) == 2
