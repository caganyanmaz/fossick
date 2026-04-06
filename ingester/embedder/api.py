from __future__ import annotations

import httpx
from loguru import logger

from ingester.config import ApiEmbeddingConfig
from ingester.embedder.base import BaseEmbedder

_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/embeddings",
    "voyageai": "https://api.voyageai.com/v1/embeddings",
}

_BATCH_SIZE = 100


class ApiEmbedder(BaseEmbedder):
    def __init__(self, config: ApiEmbeddingConfig) -> None:
        api_key = config.api_key.get_secret_value()
        if not api_key:
            raise ValueError(
                "embedding.api.api_key is required for the API embedder "
                "(or set the EMBEDDING_API_KEY environment variable)"
            )
        if config.provider not in _ENDPOINTS:
            raise ValueError(
                f"Unknown embedding provider: {config.provider!r}. "
                f"Supported: {list(_ENDPOINTS)}"
            )
        self._endpoint = _ENDPOINTS[config.provider]
        self._model = config.model
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        self._dimension: int | None = None
        logger.info("API embedder initialised: provider={} model={}", config.provider, config.model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            response = self._client.post(
                self._endpoint,
                json={"input": batch, "model": self._model},
            )
            response.raise_for_status()
            data = response.json()["data"]
            results.extend(item["embedding"] for item in data)
        return results

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            vectors = self.embed([" "])
            self._dimension = len(vectors[0])
        return self._dimension
