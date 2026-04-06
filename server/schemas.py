from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    file_path: str
    filename: str
    filetype: str
    score: float
    snippet: str
    modified_at: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    took_ms: float


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class IndexRequest(BaseModel):
    path: str


class IndexResponse(BaseModel):
    status: str
    chunks: int = 0
    error: str = ""


class DeleteResponse(BaseModel):
    status: str


class HealthResponse(BaseModel):
    status: str
    indexed_files: int
    qdrant: str


class FileListItem(BaseModel):
    id: int
    path: str
    filename: str
    filetype: str
    size_bytes: int | None = None
    indexed_at: str | None = None
    status: str
