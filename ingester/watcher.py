from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

if TYPE_CHECKING:
    from ingester.pipeline import Pipeline

DEBOUNCE_SECONDS = 2.0
_IGNORED_PREFIXES = (".", "~")
_IGNORED_SUFFIXES = (".swp",)


class _IngestEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        event_queue: asyncio.Queue[str],
        pipeline: Pipeline,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._queue = event_queue
        self._pipeline = pipeline
        self._loop = loop
        self._last_seen: dict[str, float] = {}

    def _should_ignore(self, path: str) -> bool:
        name = Path(path).name
        return name.startswith(_IGNORED_PREFIXES) or name.endswith(_IGNORED_SUFFIXES)

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory or self._should_ignore(event.src_path):
            return
        self._enqueue(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory or self._should_ignore(event.src_path):
            return
        self._enqueue(event.src_path)

    def on_deleted(self, event: FileDeletedEvent) -> None:  # type: ignore[override]
        if event.is_directory or self._should_ignore(event.src_path):
            return
        logger.info(f"File deleted, removing from index: {event.src_path}")
        asyncio.run_coroutine_threadsafe(
            self._pipeline.delete(event.src_path), self._loop
        )

    def _enqueue(self, path: str) -> None:
        now = time.monotonic()
        last = self._last_seen.get(path, 0.0)
        if now - last < DEBOUNCE_SECONDS:
            logger.debug(f"Debounced event for: {path}")
            return
        self._last_seen[path] = now
        asyncio.run_coroutine_threadsafe(self._queue.put(path), self._loop)
        logger.debug(f"Queued for ingestion: {path}")


class FileWatcher:
    def __init__(
        self,
        directories: list[str],
        event_queue: asyncio.Queue[str],
        pipeline: Pipeline,
    ) -> None:
        self._directories = directories
        self._queue = event_queue
        self._pipeline = pipeline
        self._observer: Observer | None = None

    def start(self) -> None:
        loop = asyncio.get_event_loop()
        handler = _IngestEventHandler(self._queue, self._pipeline, loop)
        self._observer = Observer()
        for directory in self._directories:
            self._observer.schedule(handler, directory, recursive=True)
            logger.info(f"Watching directory: {directory}")
        self._observer.start()
        logger.info("FileWatcher started.")

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        logger.info("FileWatcher stopped.")
