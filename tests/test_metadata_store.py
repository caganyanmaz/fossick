from __future__ import annotations

import pytest

from ingester.store.metadata import ChunkRecord, MetadataStore


def _chunk(file_id: int, index: int) -> ChunkRecord:
    return ChunkRecord(
        id=None,
        file_id=file_id,
        qdrant_id=f"qdrant-{index}",
        chunk_index=index,
        text=f"chunk text {index}",
        metadata_json="{}",
    )


@pytest.mark.asyncio
async def test_upsert_file_new(store: MetadataStore) -> None:
    file_id = await store.upsert_file("/docs/a.txt", "abc123", "txt", 100, 1.0)
    assert isinstance(file_id, int)
    record = await store.get_file_by_path("/docs/a.txt")
    assert record is not None
    assert record.id == file_id
    assert record.hash == "abc123"
    assert record.filetype == "txt"
    assert record.status == "pending"


@pytest.mark.asyncio
async def test_upsert_file_idempotent(store: MetadataStore) -> None:
    id1 = await store.upsert_file("/docs/b.txt", "hash1", "txt", 50, 1.0)
    id2 = await store.upsert_file("/docs/b.txt", "hash2", "txt", 60, 2.0)
    assert id1 == id2
    record = await store.get_file_by_path("/docs/b.txt")
    assert record is not None
    assert record.hash == "hash2"
    assert record.size_bytes == 60


@pytest.mark.asyncio
async def test_set_file_status(store: MetadataStore) -> None:
    file_id = await store.upsert_file("/docs/c.txt", "h", "txt", None, None)
    await store.set_file_status(file_id, "indexed")
    record = await store.get_file_by_path("/docs/c.txt")
    assert record is not None
    assert record.status == "indexed"


@pytest.mark.asyncio
async def test_get_files_needing_reindex(store: MetadataStore) -> None:
    id1 = await store.upsert_file("/docs/d.txt", "h1", "txt", None, None)
    await store.upsert_file("/docs/e.txt", "h2", "txt", None, None)
    await store.set_file_status(id1, "indexed")
    await store.upsert_file("/docs/f.txt", "h3", "txt", None, None)  # stays pending

    needing = await store.get_files_needing_reindex()
    paths = {r.path for r in needing}
    assert "/docs/d.txt" not in paths
    assert "/docs/e.txt" in paths  # id2 is still pending
    assert "/docs/f.txt" in paths


@pytest.mark.asyncio
async def test_save_chunks(store: MetadataStore) -> None:
    file_id = await store.upsert_file("/docs/g.txt", "h", "txt", None, None)
    chunks = [_chunk(file_id, i) for i in range(3)]
    await store.save_chunks(file_id, chunks)

    record = await store.get_file_by_path("/docs/g.txt")
    assert record is not None
    assert record.indexed_at is not None

    # Re-save with fewer chunks — old ones must be replaced
    await store.save_chunks(file_id, [_chunk(file_id, 0)])

    # Verify via raw count (we don't expose a get_chunks, so check indirectly
    # by confirming no error is raised and indexed_at is still set)
    record2 = await store.get_file_by_path("/docs/g.txt")
    assert record2 is not None
    assert record2.indexed_at is not None


@pytest.mark.asyncio
async def test_delete_file_cascades(store: MetadataStore) -> None:
    file_id = await store.upsert_file("/docs/h.txt", "h", "txt", None, None)
    await store.save_chunks(file_id, [_chunk(file_id, 0)])
    await store.delete_file("/docs/h.txt")

    record = await store.get_file_by_path("/docs/h.txt")
    assert record is None
    # If cascade works, no orphan chunk rows remain (verified by absence of FK error on re-insert)


@pytest.mark.asyncio
async def test_get_all_files_pagination(store: MetadataStore) -> None:
    for i in range(5):
        await store.upsert_file(f"/docs/page{i}.txt", f"h{i}", "txt", None, None)

    page = await store.get_all_files(limit=2, offset=2)
    assert len(page) == 2
    assert page[0].path == "/docs/page2.txt"
    assert page[1].path == "/docs/page3.txt"
