from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from ingester.chunker import Chunker
from ingester.embedder.base import BaseEmbedder
from ingester.parser.registry import get_parser
from ingester.store.metadata import ChunkRecord, MetadataStore
from ingester.store.vector import VectorPoint, VectorStore, _build_sparse_vector


@dataclass
class IngestResult:
    path: str
    status: str  # "indexed" | "skipped" | "error" | "unsupported"
    chunks: int = 0
    error: str = ""


class Pipeline:
    def __init__(
        self,
        config: Any,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        embedder: BaseEmbedder,
    ) -> None:
        self._config = config
        self._metadata = metadata_store
        self._vectors = vector_store
        self._embedder = embedder
        self._chunker = Chunker()

    async def ingest(self, path: str) -> IngestResult:
        """Full pipeline for one file. Idempotent — safe to call multiple times."""
        # 1. Compute sha256 hash
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            logger.warning("Cannot read file {}: {}", path, exc)
            return IngestResult(path=path, status="error", error=str(exc))

        file_hash = hashlib.sha256(data).hexdigest()

        # 2. Skip if already indexed with same hash
        existing = await self._metadata.get_file_by_path(path)
        if existing is not None and existing.hash == file_hash and existing.status == "indexed":
            logger.debug("skipping unchanged file {}", path)
            return IngestResult(path=path, status="skipped")

        # 3. Find parser
        parser = get_parser(path)
        if parser is None:
            logger.debug("no parser for {}", path)
            return IngestResult(path=path, status="unsupported")

        # 4. Parse
        try:
            parsed_doc = parser.parse(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("parse error for {}: {}", path, exc)
            return IngestResult(path=path, status="error", error=str(exc))

        # 5. Chunk
        chunks = self._chunker.chunk(parsed_doc)
        if not chunks:
            logger.warning("no chunks produced for {}", path)

        # 6. Embed
        dense_vectors: list[list[float]] = []
        if chunks:
            dense_vectors = self._embedder.embed([c.text for c in chunks])

        # 7–8. Build VectorPoints with sparse vectors
        points: list[VectorPoint] = []
        qdrant_ids: list[str] = []
        for i, chunk in enumerate(chunks):
            point_id = str(uuid.uuid4())
            qdrant_ids.append(point_id)
            sparse_vec = _build_sparse_vector(chunk.text)
            payload: dict[str, Any] = {
                **chunk.metadata,
                "text": chunk.raw_text,
                "chunk_index": chunk.chunk_index,
                "source_path": path,
            }
            points.append(
                VectorPoint(
                    id=point_id,
                    dense_vector=dense_vectors[i],
                    sparse_vector=sparse_vec if sparse_vec else None,
                    payload=payload,
                )
            )

        # Clean up old Qdrant vectors if re-indexing a changed file
        if existing is not None:
            old_ids = await self._metadata.get_chunk_qdrant_ids(existing.id)
            if old_ids:
                await self._vectors.delete(old_ids)

        # 9. Upsert to Qdrant
        if points:
            await self._vectors.upsert(points)

        # 10. Save to SQLite
        stat = Path(path).stat()
        filetype = Path(path).suffix.lstrip(".").lower() or "unknown"
        file_id = await self._metadata.upsert_file(
            path=path,
            hash=file_hash,
            filetype=filetype,
            size=stat.st_size,
            mtime=stat.st_mtime,
        )

        chunk_records = [
            ChunkRecord(
                id=None,
                file_id=file_id,
                qdrant_id=qdrant_ids[i],
                chunk_index=chunk.chunk_index,
                text=chunk.raw_text,
                metadata_json=json.dumps(chunk.metadata),
            )
            for i, chunk in enumerate(chunks)
        ]
        await self._metadata.save_chunks(file_id, chunk_records)

        # 11. Mark as indexed
        await self._metadata.set_file_status(file_id, "indexed")

        logger.info("indexed {} ({} chunks)", path, len(chunks))

        # 12. Return result
        return IngestResult(path=path, status="indexed", chunks=len(chunks))

    async def delete(self, path: str) -> None:
        """Remove a file and all its chunks from both stores."""
        record = await self._metadata.get_file_by_path(path)
        if record is None:
            return

        qdrant_ids = await self._metadata.get_chunk_qdrant_ids(record.id)
        if qdrant_ids:
            await self._vectors.delete(qdrant_ids)

        await self._metadata.delete_file(path)
        logger.info("deleted {}", path)

    async def ingest_directory(self, directory: str) -> list[IngestResult]:
        """Ingest all files in a directory recursively."""
        results: list[IngestResult] = []
        for p in Path(directory).rglob("*"):
            if p.is_file():
                result = await self.ingest(str(p))
                results.append(result)
        return results
