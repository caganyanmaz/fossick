from loguru import logger
from sentence_transformers import SentenceTransformer

from ingester.config import LocalEmbeddingConfig
from ingester.embedder.base import BaseEmbedder


class LocalEmbedder(BaseEmbedder):
    def __init__(self, config: LocalEmbeddingConfig) -> None:
        logger.info("Loading local embedding model: {}", config.model)
        self._model = SentenceTransformer(config.model)
        self._batch_size = config.batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=False,
        )
        return [v.tolist() for v in vectors]

    @property
    def dimension(self) -> int:
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError("Model did not return an embedding dimension")
        return int(dim)
