"""API tests using FastAPI TestClient with mocked dependencies.

Tests do not require a running Qdrant or SQLite instance.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ingester.pipeline import IngestResult
from ingester.store.metadata import FileRecord
from ingester.store.vector import SearchResult as VectorSearchResult
from server.dependencies import (
    get_config,
    get_embedder,
    get_metadata_store,
    get_pipeline,
    get_vector_store,
)
from server.main import create_app


def _make_file_record(path: str = "/data/sample.txt") -> FileRecord:
    return FileRecord(
        id=1,
        path=path,
        hash="abc123",
        filetype="txt",
        size_bytes=1024,
        created_at=1700000000.0,
        modified_at=1700000000.0,
        indexed_at=1700000000.0,
        status="indexed",
    )


def _make_vector_result(source_path: str = "/data/sample.txt") -> VectorSearchResult:
    return VectorSearchResult(
        id="uuid-001",
        score=0.92,
        payload={
            "text": "This is a sample chunk of text from the document.",
            "source_path": source_path,
            "filetype": "txt",
            "filename": "sample.txt",
            "modified_at": 1700000000.0,
        },
    )


@pytest_asyncio.fixture
async def client():
    """AsyncClient with all dependencies mocked via dependency_overrides."""
    app = create_app()

    # ── mocks ──────────────────────────────────────────────────────────────────
    mock_pipeline = MagicMock()
    mock_pipeline.ingest = AsyncMock(
        return_value=IngestResult(path="/data/sample.txt", status="indexed", chunks=3)
    )
    mock_pipeline.delete = AsyncMock(return_value=None)

    mock_vector_store = MagicMock()
    mock_vector_store.search = AsyncMock(return_value=[_make_vector_result()])
    mock_vector_store.collection_info = AsyncMock(return_value={"status": "green"})

    mock_metadata_store = MagicMock()
    mock_metadata_store.get_all_files = AsyncMock(return_value=[_make_file_record()])
    mock_metadata_store.count_files = AsyncMock(return_value=1)

    mock_embedder = MagicMock()
    mock_embedder.embed = MagicMock(return_value=[[0.1] * 384])
    mock_embedder.dimension = 384

    mock_config = MagicMock()
    mock_config.llm.backend = "api"
    mock_config.llm.api.provider = "anthropic"
    mock_config.llm.api.model = "claude-haiku-4-5-20251001"
    mock_config.llm.api.api_key.get_secret_value.return_value = "test-key"

    # ── override dependencies ──────────────────────────────────────────────────
    app.dependency_overrides[get_pipeline] = lambda: mock_pipeline
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_metadata_store] = lambda: mock_metadata_store
    app.dependency_overrides[get_embedder] = lambda: mock_embedder
    app.dependency_overrides[get_config] = lambda: mock_config

    # ── pre-populate app.state for endpoints that read it directly ─────────────
    app.state.pipeline = mock_pipeline
    app.state.vector_store = mock_vector_store
    app.state.metadata_store = mock_metadata_store
    app.state.embedder = mock_embedder
    app.state.config = mock_config

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://test",
    ) as c:
        yield c, mock_pipeline, mock_metadata_store, mock_vector_store

    app.dependency_overrides.clear()


# ─── /health ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_ok(client: Any) -> None:
    c, *_ = client
    r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["indexed_files"] == 1
    assert body["qdrant"] == "ok"


# ─── /search ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_results(client: Any) -> None:
    c, *_ = client
    r = await c.get("/search", params={"q": "sample document"})
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert body["query"] == "sample document"
    assert isinstance(body["took_ms"], float)
    assert len(body["results"]) >= 1
    result = body["results"][0]
    assert result["filetype"] == "txt"
    assert result["score"] == pytest.approx(0.92, abs=0.01)
    assert "sample" in result["snippet"]


@pytest.mark.asyncio
async def test_search_missing_query_returns_422(client: Any) -> None:
    c, *_ = client
    r = await c.get("/search")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_with_filetype_filter(client: Any) -> None:
    c, _, __, mock_vs = client
    r = await c.get("/search", params={"q": "hello", "filetype": "pdf"})
    assert r.status_code == 200
    # vector_store.search was called with filters including filetype
    call_kwargs = mock_vs.search.call_args
    assert call_kwargs is not None
    filters_arg = (
        call_kwargs.args[3] if len(call_kwargs.args) > 3 else call_kwargs.kwargs.get("filters")
    )
    assert filters_arg == {"filetype": "pdf"}


# ─── /index ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_post_calls_pipeline(client: Any) -> None:
    c, mock_pipeline, *_ = client
    r = await c.post("/index", json={"path": "/data/sample.txt"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "indexed"
    assert body["chunks"] == 3
    mock_pipeline.ingest.assert_called_once_with("/data/sample.txt")


@pytest.mark.asyncio
async def test_index_delete_calls_pipeline(client: Any) -> None:
    c, mock_pipeline, *_ = client
    r = await c.request("DELETE", "/index", json={"path": "/data/sample.txt"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    mock_pipeline.delete.assert_called_once_with("/data/sample.txt")


# ─── /files ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_files_returns_list(client: Any) -> None:
    c, _, mock_meta, __ = client
    r = await c.get("/files")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) == 1
    item = items[0]
    assert item["filename"] == "sample.txt"
    assert item["filetype"] == "txt"
    assert item["status"] == "indexed"


@pytest.mark.asyncio
async def test_files_pagination_params(client: Any) -> None:
    c, _, mock_meta, __ = client
    await c.get("/files", params={"limit": 10, "offset": 20})
    mock_meta.get_all_files.assert_called_with(limit=10, offset=20, filetype=None)


@pytest.mark.asyncio
async def test_files_filetype_filter(client: Any) -> None:
    c, _, mock_meta, __ = client
    await c.get("/files", params={"filetype": "pdf"})
    mock_meta.get_all_files.assert_called_with(limit=50, offset=0, filetype="pdf")


# ─── /chat ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sse_stream(client: Any) -> None:
    """Chat endpoint returns text/event-stream with SSE data lines."""
    c, *_ = client

    # Build a mock async context manager that yields canned SSE lines
    sse_lines = [
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}}',
        'data: {"type": "message_stop"}',
    ]

    class FakeStream:
        async def __aenter__(self) -> FakeStream:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        async def aiter_lines(self):  # type: ignore[override]
            for line in sse_lines:
                yield line

    class FakeAsyncClient:
        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        def stream(self, *args: object, **kwargs: object) -> FakeStream:
            return FakeStream()

    with patch("server.routes.chat.httpx.AsyncClient", return_value=FakeAsyncClient()):
        r = await c.post(
            "/chat",
            json={"message": "What is in my files?", "history": [], "top_k": 3},
        )

    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    body = r.text
    assert "data:" in body
    # Final done event should be present
    assert '"done"' in body
