from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ingester.embedder.base import BaseEmbedder
from ingester.store.vector import SearchResult as VectorSearchResult
from ingester.store.vector import VectorStore, _build_sparse_vector
from server.dependencies import get_embedder, get_vector_store
from server.schemas import SearchResponse, SearchResult

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search(
    q: Annotated[str, Query(min_length=1)],
    top_k: Annotated[int, Query(ge=1, le=100)] = 10,
    filetype: str | None = None,
    path_prefix: str | None = None,
    embedder: Annotated[BaseEmbedder, Depends(get_embedder)] = ...,  # type: ignore[assignment]
    vector_store: Annotated[VectorStore, Depends(get_vector_store)] = ...,  # type: ignore[assignment]
) -> SearchResponse:
    t0 = time.monotonic()

    loop = asyncio.get_running_loop()
    dense: list[float] = (await loop.run_in_executor(None, embedder.embed, [q]))[0]
    sparse = _build_sparse_vector(q)

    filters = {"filetype": filetype} if filetype else None
    fetch_k = top_k * 2 if path_prefix else top_k
    raw: list[VectorSearchResult] = await vector_store.search(
        dense, sparse, fetch_k, filters
    )

    results: list[SearchResult] = []
    for r in raw:
        src = r.payload.get("source_path", "")
        if path_prefix and not src.startswith(path_prefix):
            continue
        modified_raw = r.payload.get("modified_at")
        modified_str: str | None = None
        if isinstance(modified_raw, (int, float)):
            from datetime import datetime

            modified_str = datetime.fromtimestamp(float(modified_raw)).isoformat()
        results.append(
            SearchResult(
                file_path=src,
                filename=Path(src).name if src else "",
                filetype=r.payload.get("filetype", ""),
                score=r.score,
                snippet=(r.payload.get("text", ""))[:200],
                modified_at=modified_str,
            )
        )
        if len(results) >= top_k:
            break

    took_ms = (time.monotonic() - t0) * 1000
    return SearchResponse(results=results, query=q, took_ms=took_ms)
