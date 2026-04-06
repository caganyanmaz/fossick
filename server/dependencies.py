from __future__ import annotations

from fastapi import Request

from ingester.config import AppConfig
from ingester.embedder.base import BaseEmbedder
from ingester.pipeline import Pipeline
from ingester.store.metadata import MetadataStore
from ingester.store.vector import VectorStore


def get_config(request: Request) -> AppConfig:
    return request.app.state.config  # type: ignore[no-any-return]


def get_pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline  # type: ignore[no-any-return]


def get_metadata_store(request: Request) -> MetadataStore:
    return request.app.state.metadata_store  # type: ignore[no-any-return]


def get_vector_store(request: Request) -> VectorStore:
    return request.app.state.vector_store  # type: ignore[no-any-return]


def get_embedder(request: Request) -> BaseEmbedder:
    return request.app.state.embedder  # type: ignore[no-any-return]
