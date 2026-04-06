"""Tests for the embedder module.

Local embedder tests use the real all-MiniLM-L6-v2 model (downloaded on first run).
API embedder tests mock httpx.Client.post — no real network calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ingester.config import ApiEmbeddingConfig, EmbeddingConfig, LocalEmbeddingConfig
from ingester.embedder import get_embedder
from ingester.embedder.api import ApiEmbedder
from ingester.embedder.local import LocalEmbedder

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MODEL = "all-MiniLM-L6-v2"
DIMENSION = 384


@pytest.fixture(scope="module")
def local_embedder() -> LocalEmbedder:
    return LocalEmbedder(LocalEmbeddingConfig(model=MODEL, batch_size=32))


def _make_api_config(provider: str = "openai") -> ApiEmbeddingConfig:
    return ApiEmbeddingConfig(provider=provider, model="text-embedding-3-small", api_key="sk-test")


def _mock_response(embeddings: list[list[float]]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "data": [{"embedding": e, "index": i} for i, e in enumerate(embeddings)]
    }
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Local embedder tests
# ---------------------------------------------------------------------------


def test_local_embed_returns_correct_shape(local_embedder: LocalEmbedder) -> None:
    result = local_embedder.embed(["hello world", "foo bar"])
    assert len(result) == 2
    assert len(result[0]) == DIMENSION
    assert len(result[1]) == DIMENSION


def test_local_dimension_property(local_embedder: LocalEmbedder) -> None:
    assert local_embedder.dimension == DIMENSION


def test_local_batch_size_respected(local_embedder: LocalEmbedder) -> None:
    texts = [f"sentence {i}" for i in range(50)]
    result = local_embedder.embed(texts)
    assert len(result) == 50
    assert all(len(v) == DIMENSION for v in result)


def test_local_empty_input(local_embedder: LocalEmbedder) -> None:
    assert local_embedder.embed([]) == []


# ---------------------------------------------------------------------------
# API embedder tests
# ---------------------------------------------------------------------------


def test_api_missing_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        ApiEmbedder(ApiEmbeddingConfig(api_key=""))


def test_api_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        ApiEmbedder(ApiEmbeddingConfig(provider="unknown_provider", api_key="sk-test"))


def test_api_embed_openai() -> None:
    fake_vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    with patch("httpx.Client.post", return_value=_mock_response(fake_vectors)) as mock_post:
        embedder = ApiEmbedder(_make_api_config("openai"))
        result = embedder.embed(["text one", "text two"])

    assert result == fake_vectors
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "openai.com" in call_kwargs.args[0]
    body = call_kwargs.kwargs["json"]
    assert body["input"] == ["text one", "text two"]


def test_api_embed_voyageai() -> None:
    fake_vectors = [[0.7, 0.8, 0.9]]
    with patch("httpx.Client.post", return_value=_mock_response(fake_vectors)) as mock_post:
        embedder = ApiEmbedder(_make_api_config("voyageai"))
        result = embedder.embed(["voyage text"])

    assert result == fake_vectors
    call_url = mock_post.call_args.args[0]
    assert "voyageai.com" in call_url


def test_api_batching() -> None:
    """150 texts → 2 POST calls (batch of 100 + batch of 50)."""
    texts = [f"t{i}" for i in range(150)]
    batch1 = [[float(i)] * 3 for i in range(100)]
    batch2 = [[float(i)] * 3 for i in range(50)]

    responses = [_mock_response(batch1), _mock_response(batch2)]
    with patch("httpx.Client.post", side_effect=responses) as mock_post:
        embedder = ApiEmbedder(_make_api_config())
        result = embedder.embed(texts)

    assert mock_post.call_count == 2
    assert len(result) == 150


def test_api_empty_input() -> None:
    with patch("httpx.Client.post") as mock_post:
        embedder = ApiEmbedder(_make_api_config())
        result = embedder.embed([])

    assert result == []
    mock_post.assert_not_called()


def test_api_dimension_cached() -> None:
    """dimension property should call embed once and cache the result."""
    fake_vector = [[0.1, 0.2, 0.3]]
    with patch("httpx.Client.post", return_value=_mock_response(fake_vector)) as mock_post:
        embedder = ApiEmbedder(_make_api_config())
        d1 = embedder.dimension
        d2 = embedder.dimension

    assert d1 == 3
    assert d2 == 3
    assert mock_post.call_count == 1  # only embedded once


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_get_embedder_local() -> None:
    config = EmbeddingConfig(backend="local")
    with patch.object(LocalEmbedder, "__init__", return_value=None):
        embedder = get_embedder(config)
    assert isinstance(embedder, LocalEmbedder)


def test_get_embedder_api() -> None:
    config = EmbeddingConfig(backend="api", api=ApiEmbeddingConfig(api_key="sk-test"))
    with patch.object(ApiEmbedder, "__init__", return_value=None):
        embedder = get_embedder(config)
    assert isinstance(embedder, ApiEmbedder)


def test_get_embedder_unknown() -> None:
    config = EmbeddingConfig(backend="llama")
    with pytest.raises(ValueError, match="Unknown embedding backend"):
        get_embedder(config)
