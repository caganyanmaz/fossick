#!/usr/bin/env python3
"""One-shot full reindex script.

Usage:
    python scripts/reindex_all.py [--config path/to/config.yaml]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from ingester.config import load_config
from ingester.embedder import get_embedder
from ingester.pipeline import IngestResult, Pipeline
from ingester.store.metadata import MetadataStore
from ingester.store.vector import VectorStore


async def run(config_path: str) -> None:
    config = load_config(config_path)

    if not config.watched_dirs:
        logger.warning("No watched_dirs configured — nothing to index.")
        return

    # Initialise stores
    metadata_store = MetadataStore(config.sqlite.path)
    await metadata_store.init()

    embedder = get_embedder(config.embedding)

    vector_store = VectorStore(config.qdrant, embedder_dimension=embedder.dimension)
    await vector_store.init()

    pipeline = Pipeline(
        config=config,
        metadata_store=metadata_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    totals: dict[str, int] = {"indexed": 0, "skipped": 0, "error": 0, "unsupported": 0}

    for directory in config.watched_dirs:
        logger.info("Scanning directory: {}", directory)
        results: list[IngestResult] = await pipeline.ingest_directory(directory)
        for result in results:
            totals[result.status] = totals.get(result.status, 0) + 1
            if result.status == "indexed":
                logger.info("  [indexed]     {} ({} chunks)", result.path, result.chunks)
            elif result.status == "error":
                logger.warning("  [error]       {} — {}", result.path, result.error)
            elif result.status == "skipped":
                logger.debug("  [skipped]     {}", result.path)

    await metadata_store.close()

    logger.info(
        "Done. indexed={} skipped={} error={} unsupported={}",
        totals.get("indexed", 0),
        totals.get("skipped", 0),
        totals.get("error", 0),
        totals.get("unsupported", 0),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-index all watched directories.")
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="PATH",
        help="Path to config.yaml (default: config.yaml)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
