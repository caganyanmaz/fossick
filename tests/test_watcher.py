# No unit tests for ingester/watcher.py and scheduler/jobs.py.
#
# Reason: Both components are integration-level by nature.
#
# - FileWatcher relies on watchdog's Observer, which spawns OS-level filesystem
#   monitoring threads. Simulating real CREATE/MODIFY/DELETE events in a unit
#   test would require temporary directories, real file operations, and careful
#   synchronisation between the watchdog thread and the asyncio event loop —
#   making tests slow, flaky, and hard to isolate.
#
# - The scheduler (APScheduler AsyncIOScheduler) drives timing-based jobs that
#   are trivial to reason about from the code but awkward to test without either
#   mocking time or waiting for real wall-clock intervals.
#
# How to verify end-to-end:
#   1. Start Qdrant:  bash scripts/setup_qdrant.sh
#   2. Run the server: uvicorn server.main:app --reload --port 8000
#   3. Add a directory to watched_dirs in config.yaml
#   4. Create or modify a file in that directory
#   5. Within watch_interval_seconds, check the logs for "Ingested ... status=indexed"
#   6. Delete the file and confirm "File deleted, removing from index" log line
