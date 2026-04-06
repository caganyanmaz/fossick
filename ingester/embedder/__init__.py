from ingester.config import EmbeddingConfig
from ingester.embedder.api import ApiEmbedder
from ingester.embedder.base import BaseEmbedder
from ingester.embedder.local import LocalEmbedder


def get_embedder(config: EmbeddingConfig) -> BaseEmbedder:
    if config.backend == "local":
        return LocalEmbedder(config.local)
    elif config.backend == "api":
        return ApiEmbedder(config.api)
    else:
        raise ValueError(f"Unknown embedding backend: {config.backend!r}")
