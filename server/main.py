from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ingester.config import load_config
from ingester.embedder import get_embedder as _build_embedder
from ingester.pipeline import Pipeline
from ingester.store.metadata import MetadataStore
from ingester.store.vector import VectorStore
from ingester.watcher import FileWatcher
from scheduler.jobs import create_scheduler
from server.dependencies import get_metadata_store, get_vector_store
from server.routes import chat, files, index, search
from server.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config = load_config()
    app.state.config = config

    metadata_store = MetadataStore(config.sqlite.path)
    await metadata_store.init()
    app.state.metadata_store = metadata_store

    loop = asyncio.get_running_loop()
    embedder = await loop.run_in_executor(None, _build_embedder, config.embedding)
    app.state.embedder = embedder

    vector_store = VectorStore(config.qdrant, embedder_dimension=embedder.dimension)
    await vector_store.init()
    app.state.vector_store = vector_store

    pipeline = Pipeline(
        config=config,
        metadata_store=metadata_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    app.state.pipeline = pipeline

    watcher: FileWatcher | None = None
    scheduler = None
    if config.watched_dirs:
        event_queue: asyncio.Queue[str] = asyncio.Queue()
        watcher = FileWatcher(config.watched_dirs, event_queue, pipeline)
        watcher.start()
        scheduler = create_scheduler(config, pipeline, watcher, event_queue)
        scheduler.start()
        logger.info("Watcher and scheduler started for {} dirs", len(config.watched_dirs))

    app.state.watcher = watcher
    app.state.scheduler = scheduler

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
    if watcher is not None:
        watcher.stop()
    await metadata_store.close()
    logger.info("Server shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(title="File Ingester", lifespan=lifespan)

    # Register dynamic routes BEFORE the static files mount so they take precedence
    app.include_router(search.router, tags=["search"])
    app.include_router(chat.router, tags=["chat"])
    app.include_router(index.router, tags=["index"])
    app.include_router(files.router, tags=["files"])

    @app.get("/health", response_model=HealthResponse)
    async def health(
        request: Request,
        metadata_store: Annotated[MetadataStore, Depends(get_metadata_store)],
        vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    ) -> HealthResponse:
        try:
            indexed_files = await metadata_store.count_files()
        except Exception:
            indexed_files = 0

        try:
            await vector_store.collection_info()
            qdrant_status = "ok"
        except Exception:
            qdrant_status = "error"

        return HealthResponse(
            status="ok",
            indexed_files=indexed_files,
            qdrant=qdrant_status,
        )

    # Static files mount last — acts as fallback, serves index.html for /
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
