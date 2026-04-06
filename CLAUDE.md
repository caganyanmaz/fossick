# File Ingester

## Commands
- Install: `pip install -e ".[dev]"`
- Run server: `uvicorn server.main:app --reload --port 8000`
- Run tests: `pytest tests/ -v`
- Start Qdrant: `bash scripts/setup_qdrant.sh`
- Lint: `ruff check . && mypy ingester/ server/`

## Constraints
- Python 3.11+, Linux only, no GPU available
- Total RAM budget: 2GB across all processes
- Embedding model runs on CPU — batch size must stay <= 32
- All backends (embedder, LLM) are swappable via config.yaml, not hardcoded
- No global state — use dependency injection via FastAPI `Depends()`
- Every public function must have a type annotation
- Never hardcode file paths — always read from config

## Code style
- Use `ruff` for formatting and linting
- Pydantic v2 for all data models
- `loguru` for logging (not stdlib logging)
- Async where it makes sense (FastAPI routes, file I/O); sync is fine for CPU-bound parsing
- Abstract base classes in `base.py` files define the interface contract

## Key architecture rules
- `ingester/` is a pure library — no FastAPI, no scheduler imports inside it
- Parser, Embedder, and Store are each behind an abstract base class so they
  can be swapped without touching the pipeline
- SQLite is the source of truth for "what is indexed" — Qdrant is derived data
  and can be rebuilt from SQLite if needed
- Chunks store the original file hash so stale embeddings can be detected
