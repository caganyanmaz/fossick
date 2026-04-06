from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio

from ingester.config import QdrantConfig
from ingester.store.vector import (
    VectorPoint,
    VectorStore,
    _build_sparse_vector,
)

DIMENSION = 4


def _uid() -> str:
    return str(uuid.uuid4())


def _point(
    vec: list[float],
    sparse: dict[int, float] | None = None,
    **payload: Any,
) -> VectorPoint:
    return VectorPoint(
        id=_uid(),
        dense_vector=vec,
        sparse_vector=sparse,
        payload=dict(payload),
    )


@pytest_asyncio.fixture
async def store() -> AsyncGenerator[VectorStore, None]:
    cfg = QdrantConfig(
        host=":memory:",
        port=6333,
        collection="test_col",
        on_disk_vectors=False,
        quantization="none",
    )
    vs = VectorStore(cfg, embedder_dimension=DIMENSION)
    await vs.init()
    yield vs


# ---------------------------------------------------------------------------
# VectorStore integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collection_creation(store: VectorStore) -> None:
    info = await store.collection_info()
    assert isinstance(info, dict)


@pytest.mark.asyncio
async def test_upsert_and_dense_search(store: VectorStore) -> None:
    p1 = _point([1.0, 0.0, 0.0, 0.0], filetype="pdf")
    p2 = _point([0.0, 1.0, 0.0, 0.0], filetype="txt")
    p3 = _point([0.0, 0.0, 1.0, 0.0], filetype="md")
    await store.upsert([p1, p2, p3])

    results = await store.search(query_dense=[1.0, 0.0, 0.0, 0.0], top_k=3)
    assert len(results) >= 1
    assert results[0].id == p1.id
    assert isinstance(results[0].score, float)


@pytest.mark.asyncio
async def test_search_returns_payload(store: VectorStore) -> None:
    p = _point([1.0, 0.0, 0.0, 0.0], filename="report.pdf", filetype="pdf")
    await store.upsert([p])

    results = await store.search(query_dense=[1.0, 0.0, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0].payload["filename"] == "report.pdf"
    assert results[0].payload["filetype"] == "pdf"


@pytest.mark.asyncio
async def test_hybrid_search(store: VectorStore) -> None:
    sparse = _build_sparse_vector("python tutorial")
    p1 = _point([1.0, 0.0, 0.0, 0.0], sparse=sparse, topic="python")
    p2 = _point([0.0, 1.0, 0.0, 0.0], topic="other")
    await store.upsert([p1, p2])

    query_sparse = _build_sparse_vector("python tutorial")
    results = await store.search(
        query_dense=[1.0, 0.0, 0.0, 0.0],
        query_sparse=query_sparse,
        top_k=5,
    )
    assert len(results) >= 1
    ids = [r.id for r in results]
    assert p1.id in ids


@pytest.mark.asyncio
async def test_search_with_filter(store: VectorStore) -> None:
    p_pdf = _point([1.0, 0.0, 0.0, 0.0], filetype="pdf")
    p_txt = _point([1.0, 0.0, 0.0, 0.0], filetype="txt")
    await store.upsert([p_pdf, p_txt])

    results = await store.search(
        query_dense=[1.0, 0.0, 0.0, 0.0],
        top_k=5,
        filters={"filetype": "pdf"},
    )
    assert len(results) >= 1
    assert all(r.payload["filetype"] == "pdf" for r in results)
    assert all(r.id != p_txt.id for r in results)


@pytest.mark.asyncio
async def test_delete(store: VectorStore) -> None:
    p1 = _point([1.0, 0.0, 0.0, 0.0], keep=True)
    p2 = _point([1.0, 0.0, 0.0, 0.0], keep=False)
    await store.upsert([p1, p2])

    await store.delete([p2.id])

    results = await store.search(query_dense=[1.0, 0.0, 0.0, 0.0], top_k=10)
    ids = [r.id for r in results]
    assert p2.id not in ids
    assert p1.id in ids


@pytest.mark.asyncio
async def test_upsert_empty_noop(store: VectorStore) -> None:
    await store.upsert([])  # must not raise


@pytest.mark.asyncio
async def test_delete_empty_noop(store: VectorStore) -> None:
    await store.delete([])  # must not raise


@pytest.mark.asyncio
async def test_collection_info_returns_dict(store: VectorStore) -> None:
    info = await store.collection_info()
    assert isinstance(info, dict)


# ---------------------------------------------------------------------------
# _build_sparse_vector unit tests (no fixture needed, synchronous)
# ---------------------------------------------------------------------------


def test_build_sparse_vector_empty() -> None:
    assert _build_sparse_vector("") == {}


def test_build_sparse_vector_whitespace_only() -> None:
    assert _build_sparse_vector("   \t\n  ") == {}


def test_build_sparse_vector_basic() -> None:
    # "hello" appears twice, "world" once — hello should have higher TF-IDF
    result = _build_sparse_vector("hello world hello")
    assert isinstance(result, dict)
    assert len(result) >= 1
    # Get scores by re-deriving the token IDs
    import hashlib

    hello_id = int.from_bytes(hashlib.md5(b"hello").digest()[:3], "little")
    world_id = int.from_bytes(hashlib.md5(b"world").digest()[:3], "little")
    assert hello_id in result
    assert world_id in result
    assert result[hello_id] > result[world_id]


def test_build_sparse_vector_all_values_positive() -> None:
    result = _build_sparse_vector("the quick brown fox jumps")
    assert all(v > 0 for v in result.values())


def test_build_sparse_vector_stable_ids() -> None:
    r1 = _build_sparse_vector("foo bar baz")
    r2 = _build_sparse_vector("foo bar baz")
    assert r1 == r2
    assert set(r1.keys()) == set(r2.keys())


def test_build_sparse_vector_no_duplicate_keys() -> None:
    result = _build_sparse_vector("alpha beta gamma delta epsilon")
    assert len(result) == len(set(result.keys()))


def test_build_sparse_vector_single_token() -> None:
    result = _build_sparse_vector("word")
    assert len(result) == 1
    assert list(result.values())[0] > 0
