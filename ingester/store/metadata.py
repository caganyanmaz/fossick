from __future__ import annotations

import time

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class FileRecord(BaseModel):
    id: int
    path: str
    hash: str
    filetype: str
    size_bytes: int | None
    created_at: float | None
    modified_at: float | None
    indexed_at: float | None
    status: str  # "pending" | "indexed" | "error"


class ChunkRecord(BaseModel):
    id: int | None  # None before insert
    file_id: int
    qdrant_id: str  # UUID
    chunk_index: int
    text: str  # raw chunk text
    metadata_json: str  # JSON string


_CREATE_FILES = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT UNIQUE NOT NULL,
    hash        TEXT NOT NULL,
    filetype    TEXT NOT NULL,
    size_bytes  INTEGER,
    created_at  REAL,
    modified_at REAL,
    indexed_at  REAL,
    status      TEXT NOT NULL DEFAULT 'pending'
)
"""

_CREATE_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    qdrant_id     TEXT NOT NULL,
    chunk_index   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    metadata_json TEXT
)
"""


def _enable_fk(dbapi_conn: object, _: object) -> None:
    cursor = getattr(dbapi_conn, "cursor")()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class MetadataStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._engine: AsyncEngine | None = None

    async def init(self) -> None:
        url = f"sqlite+aiosqlite:///{self._db_path}"
        self._engine = create_async_engine(url, future=True)
        event.listen(self._engine.sync_engine, "connect", _enable_fk)
        async with self._engine.begin() as conn:
            await conn.execute(text(_CREATE_FILES))
            await conn.execute(text(_CREATE_CHUNKS))
        logger.debug("MetadataStore initialised at {}", self._db_path)

    @property
    def _eng(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("MetadataStore.init() has not been called")
        return self._engine

    async def upsert_file(
        self,
        path: str,
        hash: str,
        filetype: str,
        size: int | None,
        mtime: float | None,
    ) -> int:
        now = time.time()
        async with self._eng.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO files (path, hash, filetype, size_bytes, created_at,"
                    " modified_at, status)"
                    " VALUES (:path, :hash, :filetype, :size, :now, :mtime, 'pending')"
                    " ON CONFLICT(path) DO UPDATE SET"
                    "   hash=excluded.hash,"
                    "   filetype=excluded.filetype,"
                    "   size_bytes=excluded.size_bytes,"
                    "   modified_at=excluded.modified_at,"
                    "   status='pending'"
                    " RETURNING id"
                ),
                {
                    "path": path,
                    "hash": hash,
                    "filetype": filetype,
                    "size": size,
                    "now": now,
                    "mtime": mtime,
                },
            )
            row = result.fetchone()
            file_id = int(row[0])  # type: ignore[index]
        logger.debug("upserted file id={} path={}", file_id, path)
        return file_id

    async def set_file_status(self, file_id: int, status: str) -> None:
        async with self._eng.begin() as conn:
            await conn.execute(
                text("UPDATE files SET status=:status WHERE id=:id"),
                {"status": status, "id": file_id},
            )
        logger.debug("file id={} status={}", file_id, status)

    async def get_file_by_path(self, path: str) -> FileRecord | None:
        async with self._eng.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, path, hash, filetype, size_bytes, created_at,"
                    " modified_at, indexed_at, status FROM files WHERE path=:path"
                ),
                {"path": path},
            )
            row = result.fetchone()
        if row is None:
            return None
        return FileRecord(
            id=row[0],
            path=row[1],
            hash=row[2],
            filetype=row[3],
            size_bytes=row[4],
            created_at=row[5],
            modified_at=row[6],
            indexed_at=row[7],
            status=row[8],
        )

    async def get_files_needing_reindex(self) -> list[FileRecord]:
        async with self._eng.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, path, hash, filetype, size_bytes, created_at,"
                    " modified_at, indexed_at, status FROM files WHERE status != 'indexed'"
                )
            )
            rows = result.fetchall()
        return [
            FileRecord(
                id=r[0],
                path=r[1],
                hash=r[2],
                filetype=r[3],
                size_bytes=r[4],
                created_at=r[5],
                modified_at=r[6],
                indexed_at=r[7],
                status=r[8],
            )
            for r in rows
        ]

    async def save_chunks(self, file_id: int, chunks: list[ChunkRecord]) -> None:
        now = time.time()
        async with self._eng.begin() as conn:
            await conn.execute(
                text("DELETE FROM chunks WHERE file_id=:fid"),
                {"fid": file_id},
            )
            for chunk in chunks:
                await conn.execute(
                    text(
                        "INSERT INTO chunks (file_id, qdrant_id, chunk_index, text, metadata_json)"
                        " VALUES (:fid, :qid, :ci, :text, :meta)"
                    ),
                    {
                        "fid": file_id,
                        "qid": chunk.qdrant_id,
                        "ci": chunk.chunk_index,
                        "text": chunk.text,
                        "meta": chunk.metadata_json,
                    },
                )
            await conn.execute(
                text("UPDATE files SET indexed_at=:now WHERE id=:id"),
                {"now": now, "id": file_id},
            )
        logger.debug("saved {} chunks for file_id={}", len(chunks), file_id)

    async def get_chunk_qdrant_ids(self, file_id: int) -> list[str]:
        async with self._eng.begin() as conn:
            result = await conn.execute(
                text("SELECT qdrant_id FROM chunks WHERE file_id=:fid"),
                {"fid": file_id},
            )
            rows = result.fetchall()
        return [r[0] for r in rows]

    async def delete_file(self, path: str) -> None:
        async with self._eng.begin() as conn:
            await conn.execute(
                text("DELETE FROM files WHERE path=:path"),
                {"path": path},
            )
        logger.debug("deleted file path={}", path)

    async def get_all_files(self, limit: int = 50, offset: int = 0) -> list[FileRecord]:
        async with self._eng.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, path, hash, filetype, size_bytes, created_at,"
                    " modified_at, indexed_at, status FROM files"
                    " ORDER BY id LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            )
            rows = result.fetchall()
        return [
            FileRecord(
                id=r[0],
                path=r[1],
                hash=r[2],
                filetype=r[3],
                size_bytes=r[4],
                created_at=r[5],
                modified_at=r[6],
                indexed_at=r[7],
                status=r[8],
            )
            for r in rows
        ]
