from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from loguru import logger
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    PointIdsList,
    PointStruct,
    Prefetch,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from ingester.config import QdrantConfig


def _build_sparse_vector(text: str) -> dict[int, float]:
    """Build a BM25-style sparse vector from text.

    Returns a dict mapping stable token IDs (24-bit MD5-based) to TF-IDF scores.
    """
    if not text:
        return {}

    tokens = [t for t in re.split(r"\W+", text.lower()) if t]
    if not tokens:
        return {}

    total = len(tokens)
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1

    result: dict[int, float] = {}
    for token, count in counts.items():
        tf = count / total
        idf = math.log(1.0 + 1.0 / tf)
        score = tf * idf
        # Stable 24-bit token ID via MD5 (avoids PYTHONHASHSEED randomization)
        token_id = int.from_bytes(hashlib.md5(token.encode()).digest()[:3], "little")
        result[token_id] = result.get(token_id, 0.0) + score

    return result


def _dict_to_sparse(d: dict[int, float]) -> SparseVector:
    indices = list(d.keys())
    values = [d[i] for i in indices]
    return SparseVector(indices=indices, values=values)


class VectorPoint(BaseModel):
    id: str  # UUID string (matches ChunkRecord.qdrant_id)
    dense_vector: list[float]
    sparse_vector: dict[int, float] | None = None
    payload: dict[str, Any]


class SearchResult(BaseModel):
    id: str
    score: float
    payload: dict[str, Any]


class VectorStore:
    def __init__(self, config: QdrantConfig, embedder_dimension: int) -> None:
        self._config = config
        self._dim = embedder_dimension
        self._client: AsyncQdrantClient | None = None

    @property
    def _cli(self) -> AsyncQdrantClient:
        if self._client is None:
            raise RuntimeError("VectorStore.init() has not been called")
        return self._client

    async def init(self) -> None:
        if self._config.host == ":memory:":
            self._client = AsyncQdrantClient(location=":memory:")
        else:
            self._client = AsyncQdrantClient(
                host=self._config.host, port=self._config.port
            )

        if await self._client.collection_exists(self._config.collection):
            logger.debug("collection '{}' already exists", self._config.collection)
            return

        quantization_config = None
        if self._config.quantization == "scalar_int8":
            quantization_config = ScalarQuantization(
                scalar=ScalarQuantizationConfig(type=ScalarType.INT8)
            )

        vectors_config = {
            "dense": VectorParams(
                size=self._dim,
                distance=Distance.COSINE,
                on_disk=self._config.on_disk_vectors,
                quantization_config=quantization_config,
            )
        }
        sparse_vectors_config = {
            "bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))
        }

        await self._client.create_collection(
            collection_name=self._config.collection,
            vectors_config=vectors_config,
            sparse_vectors_config=sparse_vectors_config,
        )
        logger.info(
            "created collection '{}' with dim={}", self._config.collection, self._dim
        )

    async def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return

        qdrant_points = []
        for p in points:
            vector: dict[str, Any] = {"dense": p.dense_vector}
            if p.sparse_vector is not None:
                vector["bm25"] = _dict_to_sparse(p.sparse_vector)
            qdrant_points.append(
                PointStruct(id=p.id, vector=vector, payload=p.payload)
            )

        await self._cli.upsert(
            collection_name=self._config.collection,
            points=qdrant_points,
            wait=True,
        )
        logger.debug("upserted {} points", len(points))

    def _build_qdrant_filter(self, filters: dict[str, Any]) -> Filter | None:
        if not filters:
            return None
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filters.items()
        ]
        return Filter(must=conditions)  # type: ignore[arg-type]

    async def search(
        self,
        query_dense: list[float],
        query_sparse: dict[int, float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        query_filter = self._build_qdrant_filter(filters or {})

        if query_sparse is None:
            response = await self._cli.query_points(
                collection_name=self._config.collection,
                query=query_dense,
                using="dense",
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        else:
            sparse_vec = _dict_to_sparse(query_sparse)
            prefetch = [
                Prefetch(
                    query=query_dense,
                    using="dense",
                    limit=top_k * 3,
                    filter=query_filter,
                ),
                Prefetch(
                    query=sparse_vec,
                    using="bm25",
                    limit=top_k * 3,
                    filter=query_filter,
                ),
            ]
            response = await self._cli.query_points(
                collection_name=self._config.collection,
                prefetch=prefetch,
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )

        return [
            SearchResult(
                id=str(point.id),
                score=point.score,
                payload=point.payload or {},
            )
            for point in response.points
        ]

    async def delete(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        await self._cli.delete(
            collection_name=self._config.collection,
            points_selector=PointIdsList(points=point_ids),  # type: ignore[arg-type]
            wait=True,
        )
        logger.debug("deleted {} points", len(point_ids))

    async def collection_info(self) -> dict[str, Any]:
        info = await self._cli.get_collection(
            collection_name=self._config.collection
        )
        return info.model_dump()
