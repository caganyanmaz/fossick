# Devlog

## 2026-04-07 — Fix server startup errors

### Problem
The server failed to start with two errors:

1. **82-second hang on startup**: `SentenceTransformer('all-MiniLM-L6-v2')` was making unauthenticated HuggingFace Hub network calls to validate/check the model on every startup, even when the model was already in the local cache (`~/.cache/huggingface/hub/`). This caused an ~82s delay before the server became ready.

2. **`FileNotFoundError` crash**: `FileWatcher.start()` would crash with `[Errno 2] No such file or directory` if any directory listed in `watched_dirs` (config.yaml) did not exist on disk. The watcher passed the path directly to `watchdog` without checking existence first.

### Fixes

**`ingester/embedder/local.py`** — Try `local_files_only=True` first when constructing `SentenceTransformer`. This skips the HF Hub network round-trip when the model is already cached. Falls back to a normal (online) load only if the model is not yet downloaded.

**`ingester/watcher.py`** — In `FileWatcher.start()`, check each directory with `Path(directory).exists()` before scheduling it. Log a warning and skip directories that don't exist rather than crashing.

### Result
Server starts in ~1 second and `/health` returns `{"status":"ok","indexed_files":0,"qdrant":"ok"}`.
