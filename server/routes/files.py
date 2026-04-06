from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ingester.store.metadata import MetadataStore
from server.dependencies import get_metadata_store
from server.schemas import FileListItem

router = APIRouter()


@router.get("/files", response_model=list[FileListItem])
async def list_files(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    filetype: str | None = None,
    metadata_store: Annotated[MetadataStore, Depends(get_metadata_store)] = ...,  # type: ignore[assignment]
) -> list[FileListItem]:
    records = await metadata_store.get_all_files(
        limit=limit, offset=offset, filetype=filetype
    )
    return [
        FileListItem(
            id=r.id,
            path=r.path,
            filename=Path(r.path).name,
            filetype=r.filetype,
            size_bytes=r.size_bytes,
            indexed_at=(
                datetime.fromtimestamp(r.indexed_at).isoformat()
                if r.indexed_at is not None
                else None
            ),
            status=r.status,
        )
        for r in records
    ]
