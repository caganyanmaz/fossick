from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio

from ingester.store.metadata import MetadataStore


@pytest_asyncio.fixture
async def store() -> AsyncGenerator[MetadataStore, None]:
    s = MetadataStore(":memory:")
    await s.init()
    yield s
