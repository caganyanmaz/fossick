from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings


class QdrantConfig(BaseModel):
    host: str = "localhost"
    port: int = 6333
    collection: str = "file_index"
    on_disk_vectors: bool = True
    quantization: str = "scalar_int8"


class SqliteConfig(BaseModel):
    path: str = "./data/index.db"


class LocalEmbeddingConfig(BaseModel):
    model: str = "all-MiniLM-L6-v2"
    batch_size: int = 32


class ApiEmbeddingConfig(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    api_key: SecretStr = SecretStr("")


class EmbeddingConfig(BaseModel):
    backend: str = "local"
    local: LocalEmbeddingConfig = LocalEmbeddingConfig()
    api: ApiEmbeddingConfig = ApiEmbeddingConfig()


class LlmApiConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    api_key: SecretStr = SecretStr("")


class LlmLocalConfig(BaseModel):
    model: str = "llama3.2:3b"
    ollama_host: str = "http://localhost:11434"


class LlmConfig(BaseModel):
    backend: str = "api"
    api: LlmApiConfig = LlmApiConfig()
    local: LlmLocalConfig = LlmLocalConfig()


class OcrConfig(BaseModel):
    backend: str = "tesseract"


class VideoConfig(BaseModel):
    keyframes: int = 10
    caption_backend: str = "local"
    transcription_backend: str = "api"


class SchedulerConfig(BaseModel):
    watch_interval_seconds: int = 300
    full_rescan_cron: str = "0 3 * * *"


class AppConfig(BaseSettings):
    watched_dirs: list[str] = []
    qdrant: QdrantConfig = QdrantConfig()
    sqlite: SqliteConfig = SqliteConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    llm: LlmConfig = LlmConfig()
    ocr: OcrConfig = OcrConfig()
    video: VideoConfig = VideoConfig()
    scheduler: SchedulerConfig = SchedulerConfig()

    model_config = {
        "env_nested_delimiter": "__",
        "env_prefix": "",
    }


def load_config(path: str = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())

    # Allow env var overrides for API keys
    import os

    if embedding_key := os.environ.get("EMBEDDING_API_KEY"):
        raw.setdefault("embedding", {}).setdefault("api", {})["api_key"] = embedding_key
    if llm_key := os.environ.get("LLM_API_KEY"):
        raw.setdefault("llm", {}).setdefault("api", {})["api_key"] = llm_key

    return AppConfig(**raw)
