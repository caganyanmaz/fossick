from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ingester.pipeline import Pipeline
from server.dependencies import get_pipeline
from server.schemas import DeleteResponse, IndexRequest, IndexResponse

router = APIRouter()


@router.post("/index", response_model=IndexResponse)
async def index_file(
    body: IndexRequest,
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
) -> IndexResponse:
    result = await pipeline.ingest(body.path)
    return IndexResponse(status=result.status, chunks=result.chunks, error=result.error)


@router.delete("/index", response_model=DeleteResponse)
async def delete_file(
    body: IndexRequest,
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
) -> DeleteResponse:
    await pipeline.delete(body.path)
    return DeleteResponse(status="ok")
