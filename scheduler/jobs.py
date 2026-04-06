from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from ingester.config import AppConfig
from ingester.pipeline import Pipeline
from ingester.watcher import FileWatcher


def create_scheduler(
    config: AppConfig,
    pipeline: Pipeline,
    watcher: FileWatcher,
    event_queue: asyncio.Queue[str],
) -> AsyncIOScheduler:
    """Create and configure the APScheduler instance with two jobs:
    - watch_loop: drains the event queue and ingests changed files
    - full_rescan: nightly full scan of all watched directories
    """
    scheduler = AsyncIOScheduler()

    async def watch_loop() -> None:
        processed = 0
        while not event_queue.empty():
            path = await event_queue.get()
            try:
                result = await pipeline.ingest(path)
                logger.info(
                    f"Ingested {path}: status={result.status} chunks={result.chunks}"
                )
            except Exception as exc:
                logger.error(f"Error ingesting {path}: {exc}")
            processed += 1
        if processed:
            logger.debug(f"watch_loop: processed {processed} queued paths")

    async def full_rescan() -> None:
        logger.info("Full rescan starting for all watched directories")
        for directory in config.watched_dirs:
            try:
                results = await pipeline.ingest_directory(directory)
                indexed = sum(1 for r in results if r.status == "indexed")
                skipped = sum(1 for r in results if r.status == "skipped")
                errors = sum(1 for r in results if r.status == "error")
                logger.info(
                    f"Rescan {directory}: {indexed} indexed, {skipped} skipped, {errors} errors"
                )
            except Exception as exc:
                logger.error(f"Error rescanning {directory}: {exc}")
        logger.info("Full rescan complete")

    scheduler.add_job(
        watch_loop,
        trigger=IntervalTrigger(seconds=config.scheduler.watch_interval_seconds),
        id="watch_loop",
        replace_existing=True,
    )

    scheduler.add_job(
        full_rescan,
        trigger=CronTrigger.from_crontab(config.scheduler.full_rescan_cron),
        id="full_rescan",
        replace_existing=True,
    )

    return scheduler
