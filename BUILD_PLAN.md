# Universal Data Ingester — Build Plan

> Hand this document to Claude Code. Work through it one phase at a time.
> Start each new phase with a fresh session (`/clear`). Use Plan Mode
> (Shift+Tab) before implementing any phase that touches multiple files.

---

## How to use this document with Claude Code

**Before you start each phase**, paste this into Claude Code:

```
Read BUILD_PLAN.md and CLAUDE.md. We are working on Phase N: [name].
Enter Plan Mode and propose a file-by-file implementation plan before
writing any code. Do not start implementing until I approve the plan.
```

**Key habits:**
- Use `Shift+Tab` to enter Plan Mode for every phase — it prevents Claude
  from spending 20 minutes solving the wrong problem.
- After each phase: `run tests, fix any failures, then stop`.
- `/clear` between phases. Accumulated context from earlier work degrades
  quality on the current task.
- Reference specific files with `@path/to/file` in your prompts.
- Add constraints explicitly: "Python 3.11+, Linux only, no GPU, max 2GB
  RAM total across all services".

---

## Repository layout

```
file-ingester/
├── CLAUDE.md                   ← Claude Code reads this automatically
├── BUILD_PLAN.md               ← this file
├── README.md
├── pyproject.toml              ← single project file (uv or pip)
├── config.yaml                 ← runtime config, not committed with secrets
├── config.example.yaml
│
├── ingester/                   ← core library (importable, no side-effects)
│   ├── __init__.py
│   ├── watcher.py              ← directory monitoring
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── base.py             ← Parser abstract base class
│   │   ├── docling_parser.py   ← PDF, DOCX, PPTX, HTML, images
│   │   ├── spreadsheet.py      ← Excel/CSV via openpyxl + pandas
│   │   ├── code.py             ← plain text + language detection
│   │   ├── video.py            ← ffmpeg keyframes + Whisper API transcript
│   │   └── registry.py         ← maps file extensions → parser class
│   ├── chunker.py              ← text splitting with metadata prefix
│   ├── embedder/
│   │   ├── __init__.py
│   │   ├── base.py             ← Embedder abstract base class
│   │   ├── local.py            ← sentence-transformers (all-MiniLM or nomic)
│   │   └── api.py              ← OpenAI / Voyage AI / Claude-compatible API
│   ├── store/
│   │   ├── __init__.py
│   │   ├── vector.py           ← Qdrant wrapper (dense + sparse BM25)
│   │   └── metadata.py         ← SQLite wrapper (file index + raw text)
│   └── pipeline.py             ← orchestrates parser → chunker → embedder → store
│
├── server/
│   ├── __init__.py
│   ├── main.py                 ← FastAPI app factory
│   ├── routes/
│   │   ├── search.py           ← GET /search
│   │   ├── chat.py             ← POST /chat (SSE)
│   │   ├── index.py            ← POST /index, DELETE /index
│   │   └── files.py            ← GET /files (browse indexed)
│   ├── schemas.py              ← Pydantic request/response models
│   └── static/
│       └── index.html          ← single-file HTMX UI
│
├── scheduler/
│   └── jobs.py                 ← APScheduler: watch loop + nightly full scan
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/               ← small sample files for each type
│   ├── test_parsers.py
│   ├── test_chunker.py
│   ├── test_pipeline.py
│   └── test_api.py
│
└── scripts/
    ├── setup_qdrant.sh         ← docker run command with correct flags
    └── reindex_all.py          ← one-shot full reindex script
```

---

## CLAUDE.md content

Create this file at the repo root before starting Phase 1.
Claude Code reads it automatically at the start of every session.

```markdown
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
```

---

## config.example.yaml

```yaml
# Copy to config.yaml and fill in values

watched_dirs:
  - /home/user/documents
  - /home/user/projects

qdrant:
  host: localhost
  port: 6333
  collection: file_index
  on_disk_vectors: true      # keeps RAM usage low
  quantization: scalar_int8  # 4x less RAM, ~2% quality loss

sqlite:
  path: ./data/index.db

embedding:
  backend: local             # "local" or "api"
  local:
    model: all-MiniLM-L6-v2  # ~90MB RAM; swap to "nomic-ai/nomic-embed-text-v1.5" for quality
    batch_size: 32
  api:
    provider: openai         # "openai" | "voyageai"
    model: text-embedding-3-small
    api_key: ""              # or set EMBEDDING_API_KEY env var

llm:
  backend: api               # "api" or "local"
  api:
    provider: anthropic
    model: claude-haiku-4-5-20251001
    api_key: ""              # or set LLM_API_KEY env var
  local:
    model: llama3.2:3b
    ollama_host: http://localhost:11434

ocr:
  backend: tesseract         # "tesseract" (local, via Docling) or "api"

video:
  keyframes: 10              # number of evenly-spaced frames to caption
  caption_backend: local     # "local" (moondream2 via Ollama) or "api"
  transcription_backend: api # "api" (Whisper API) — local is too RAM-heavy

scheduler:
  watch_interval_seconds: 300   # check for changes every 5 min
  full_rescan_cron: "0 3 * * *" # full rescan at 3am daily
```

---

## Phase 1 — Project scaffold and config

**Goal:** Repo skeleton, config loading, no real logic yet.

**Prompt for Claude Code:**
```
Read CLAUDE.md. Scaffold the repository structure from BUILD_PLAN.md.
Tasks:
1. Create pyproject.toml with all dependencies listed below.
2. Create the directory structure with empty __init__.py files.
3. Implement config.py at the root: loads config.yaml with pydantic-settings,
   supports env var overrides for secrets (api keys).
4. Create config.example.yaml exactly as shown in the build plan.
5. Write a smoke test in tests/test_config.py that loads the example config.
Run pytest after. Fix any failures before stopping.
```

**Dependencies to include in pyproject.toml:**
```toml
[project]
name = "file-ingester"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.0",
  "pydantic-settings>=2.0",
  "qdrant-client>=1.9",
  "sentence-transformers>=3.0",
  "docling>=2.0",
  "watchdog>=4.0",
  "apscheduler>=3.10",
  "sqlalchemy>=2.0",
  "aiosqlite>=0.20",
  "openpyxl>=3.1",
  "pandas>=2.0",
  "pygments>=2.18",     # language detection for code files
  "loguru>=0.7",
  "httpx>=0.27",        # async HTTP for embedding APIs
  "python-multipart>=0.0.9",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pytest-cov>=5.0",
  "ruff>=0.6",
  "mypy>=1.11",
  "httpx>=0.27",  # for TestClient
]
```

---

## Phase 2 — Metadata store (SQLite)

**Goal:** A clean SQLite layer that tracks every indexed file, its chunks,
and whether it needs re-indexing. This is built first because every other
component depends on it.

**Prompt for Claude Code:**
```
Read CLAUDE.md and @ingester/store/metadata.py.
Implement ingester/store/metadata.py with SQLAlchemy async.

Schema (two tables):

files:
  id          INTEGER PRIMARY KEY
  path        TEXT UNIQUE NOT NULL
  hash        TEXT NOT NULL        -- sha256 of file contents
  filetype    TEXT NOT NULL        -- extension without dot
  size_bytes  INTEGER
  created_at  REAL                 -- os.stat mtime
  modified_at REAL
  indexed_at  REAL                 -- when we last embedded it
  status      TEXT DEFAULT 'pending'  -- pending|indexed|error

chunks:
  id            INTEGER PRIMARY KEY
  file_id       INTEGER REFERENCES files(id) ON DELETE CASCADE
  qdrant_id     TEXT NOT NULL       -- UUID stored in Qdrant
  chunk_index   INTEGER NOT NULL    -- position within the file
  text          TEXT NOT NULL       -- raw chunk text (for re-embedding)
  metadata_json TEXT               -- JSON: filename, path, type, timestamps

Public interface (all async):
  upsert_file(path, hash, filetype, size, mtime) -> file_id
  set_file_status(file_id, status)
  get_file_by_path(path) -> FileRecord | None
  get_files_needing_reindex() -> list[FileRecord]   -- hash changed or never indexed
  save_chunks(file_id, chunks: list[ChunkRecord])
  delete_file(path)                                  -- cascades to chunks
  get_all_files(limit, offset) -> list[FileRecord]

Write tests in tests/test_metadata_store.py using an in-memory SQLite db.
Run pytest after. Fix any failures.
```

---

## Phase 3 — Parsers

**Goal:** Each parser takes a file path, returns a `ParsedDocument`
(raw text + metadata dict). They are stateless and synchronous.

**Prompt for Claude Code:**
```
Read CLAUDE.md, @ingester/parser/base.py (create it), and the build plan
parser section.

Step 1 — Define ingester/parser/base.py:

  @dataclass
  class ParsedDocument:
      text: str
      metadata: dict[str, Any]   # filename, path, filetype, size, mtime, + type-specific fields
      source_path: str

  class BaseParser(ABC):
      @abstractmethod
      def can_parse(self, path: str) -> bool: ...
      @abstractmethod
      def parse(self, path: str) -> ParsedDocument: ...

Step 2 — Implement these parsers, each in its own file:

  docling_parser.py
    Uses Docling DocumentConverter. Handles: pdf, docx, pptx, html, htm,
    md, xml. Extracts author/title/keywords from document properties if
    available. Falls back to plain text if Docling fails.

  spreadsheet.py
    Uses openpyxl for xlsx/xls, pandas for csv.
    For Excel: sheet names + each sheet as markdown table (max 1000 rows
    per sheet to avoid huge chunks). Include sheet names in metadata.

  code.py
    Plain text read. Uses pygments to detect language from extension.
    Metadata: language, line_count, has_docstring (basic heuristic).

  image.py
    If Docling OCR mode is available, use it to extract text from images.
    Otherwise return metadata only (filename, dimensions via Pillow).
    File types: jpg, jpeg, png, gif, webp, tiff, bmp.

  video.py
    Uses subprocess to call ffmpeg (must be installed on system).
    Extracts: audio as wav → calls Whisper API for transcript.
    Extracts: N evenly-spaced keyframes as JPEG → stores paths for later
    captioning (captioning happens in pipeline, not parser).
    Returns transcript text + frame paths in metadata.
    If ffmpeg is not found, log a warning and return metadata only.

Step 3 — Implement ingester/parser/registry.py:
    Maps file extensions to parser instances.
    get_parser(path) -> BaseParser | None
    Returns None for unknown types (pipeline will skip them gracefully).

Write tests in tests/test_parsers.py using the files in tests/fixtures/.
Create minimal fixture files: sample.pdf (if you can generate a trivial one),
sample.docx, sample.xlsx, sample.py, hello.txt, sample.html.
Run pytest after. Fix any failures.
```

---

## Phase 4 — Chunker

**Goal:** Split a `ParsedDocument` into overlapping text chunks, each
prefixed with a metadata header so the embedding captures file context.

**Prompt for Claude Code:**
```
Read CLAUDE.md and @ingester/chunker.py (create it).

Implement ingester/chunker.py:

  @dataclass
  class Chunk:
      text: str          -- metadata header + content
      raw_text: str      -- content only (stored in SQLite)
      metadata: dict     -- file metadata for Qdrant payload
      chunk_index: int

  class Chunker:
      def __init__(self, chunk_size: int = 512, overlap: int = 64): ...
      def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...

Behaviour:
- Build a metadata header prepended to every chunk:
    File: {filename}
    Type: {filetype}
    Path: {directory}
    Modified: {mtime as YYYY-MM-DD}
    [any type-specific fields, e.g. Sheet: Budget for xlsx]
  This lets semantic queries on filename/path work naturally.
- Split the remaining text by token count (approximate: 1 token ≈ 4 chars).
- Use a sliding window with `overlap` tokens so context is not lost at
  boundaries.
- For very short files (under 100 tokens after the header), return a single
  chunk — no splitting.
- For code files, prefer splitting on function/class boundaries (split on
  lines starting with "def ", "class ", "fn ", "func ") rather than raw
  token count. Fall back to token count if no boundaries found.

Write tests in tests/test_chunker.py.
Test: a long document produces multiple chunks with correct overlap.
Test: a short document produces exactly one chunk.
Test: metadata header appears in every chunk.
Run pytest after. Fix any failures.
```

---

## Phase 5 — Embedders

**Goal:** Two interchangeable embedder implementations behind one interface.

**Prompt for Claude Code:**
```
Read CLAUDE.md, @ingester/embedder/base.py (create it).

Step 1 — ingester/embedder/base.py:

  class BaseEmbedder(ABC):
      @abstractmethod
      def embed(self, texts: list[str]) -> list[list[float]]: ...
      @property
      @abstractmethod
      def dimension(self) -> int: ...

Step 2 — ingester/embedder/local.py:
  Uses sentence_transformers.SentenceTransformer.
  Model name comes from config. Batch size from config (default 32).
  encode() with show_progress_bar=False, convert_to_numpy=False.
  Return list[list[float]].

Step 3 — ingester/embedder/api.py:
  Supports two providers switchable by config:
  - openai: POST https://api.openai.com/v1/embeddings, model from config
  - voyageai: POST https://api.voyageai.com/v1/embeddings
  Use httpx (sync). Batch input automatically (max 100 texts per request).
  Raise a clear error if api_key is missing.

Step 4 — ingester/embedder/__init__.py:
  Factory function: get_embedder(config) -> BaseEmbedder
  Returns local or API embedder based on config.embedding.backend.

Write tests in tests/test_embedders.py.
For local: use a small model "all-MiniLM-L6-v2" and verify output shape.
For API: mock httpx with unittest.mock — do not make real API calls in tests.
Run pytest after. Fix any failures.
```

---

## Phase 6 — Vector store (Qdrant)

**Goal:** A Qdrant wrapper that stores dense + sparse vectors and exposes
clean search and upsert methods.

**Prompt for Claude Code:**
```
Read CLAUDE.md and @ingester/store/vector.py (create it).

Implement ingester/store/vector.py using qdrant_client (sync client is fine).

On initialisation:
  - Connect to Qdrant at host/port from config.
  - Create collection if it does not exist, with:
      vectors config: size=embedder.dimension, distance=Cosine
      on_disk=True (from config)
      quantization: ScalarQuantization(type=ScalarType.INT8) if configured
  - Create sparse vectors config for BM25 hybrid search (named "bm25").

Public interface:

  upsert(points: list[VectorPoint]) -> None
    VectorPoint has: id (str UUID), dense_vector, sparse_vector (optional),
    payload (dict with all file metadata + chunk text for display)

  search(query_dense: list[float],
         query_sparse: dict[int,float] | None = None,
         top_k: int = 10,
         filters: dict | None = None) -> list[SearchResult]
    SearchResult: id, score, payload

    If query_sparse is provided, use hybrid search (RRF fusion of dense
    and sparse results). Otherwise dense only.
    Filters map to Qdrant FieldCondition on payload fields.

  delete(point_ids: list[str]) -> None

  collection_info() -> dict   -- for health checks

For sparse vectors (BM25), implement a minimal TF-IDF tokenizer in the
same file as a private function _build_sparse_vector(text) -> dict[int,float].
Use a simple whitespace+punctuation tokenizer, no external dependency needed.

Write tests in tests/test_vector_store.py.
Use qdrant_client.QdrantClient(":memory:") for tests — no Docker needed.
Run pytest after. Fix any failures.
```

---

## Phase 7 — Pipeline

**Goal:** The orchestrator that wires all components together into a single
`ingest(path)` call.

**Prompt for Claude Code:**
```
Read CLAUDE.md, @ingester/pipeline.py (create it).
Read @ingester/store/metadata.py, @ingester/store/vector.py,
@ingester/parser/registry.py, @ingester/chunker.py, @ingester/embedder/__init__.py.

Implement ingester/pipeline.py:

  class Pipeline:
      def __init__(self, config, metadata_store, vector_store, embedder): ...

      async def ingest(self, path: str) -> IngestResult:
        """Full pipeline for one file. Idempotent — safe to call multiple times."""
        1. Compute sha256 hash of file.
        2. Check metadata_store: if file exists with same hash, skip (return
           IngestResult(status="skipped")).
        3. Get parser from registry. If none found, return status="unsupported".
        4. Call parser.parse(path). Catch exceptions → status="error", log warning.
        5. Call chunker.chunk(parsed_doc).
        6. Build metadata header text for each chunk.
        7. Call embedder.embed([chunk.text for chunk in chunks]).
        8. For each chunk, build sparse vector via _build_sparse_vector.
        9. Upsert to Qdrant.
        10. Save chunks to SQLite.
        11. Set file status to "indexed".
        12. Return IngestResult(status="indexed", chunks=len(chunks)).

      async def delete(self, path: str) -> None:
        """Remove a file and all its chunks from both stores."""

      async def ingest_directory(self, directory: str) -> list[IngestResult]:
        """Ingest all files in a directory recursively."""

  @dataclass
  class IngestResult:
      path: str
      status: str   -- "indexed" | "skipped" | "error" | "unsupported"
      chunks: int = 0
      error: str = ""

Write tests in tests/test_pipeline.py.
Mock the embedder to return fixed vectors (avoid loading a real model).
Test: new file gets indexed, same file with same hash is skipped,
      modified file (different hash) gets re-indexed.
Run pytest after. Fix any failures.
```

---

## Phase 8 — File watcher and scheduler

**Goal:** Background process that watches directories and triggers the
pipeline on changes.

**Prompt for Claude Code:**
```
Read CLAUDE.md, @ingester/watcher.py (create it), @scheduler/jobs.py.

Step 1 — ingester/watcher.py:
  Uses watchdog.observers.Observer + a custom FileSystemEventHandler.
  On CREATE or MODIFY events: push the path to an asyncio.Queue.
  On DELETE events: call pipeline.delete(path) directly.
  Ignore hidden files (starting with "."), temp files ("~", ".swp").
  Debounce rapid events: if the same path is queued twice within 2 seconds,
  only process it once. Use a dict of {path: timestamp} for this.

  class FileWatcher:
      def __init__(self, directories: list[str], event_queue: asyncio.Queue): ...
      def start(self) -> None: ...
      def stop(self) -> None: ...

Step 2 — scheduler/jobs.py:
  Uses APScheduler AsyncIOScheduler.
  Job 1 — watch_loop: runs every config.scheduler.watch_interval_seconds.
           Drains the event_queue and calls pipeline.ingest() for each path.
  Job 2 — full_rescan: runs on cron schedule from config.
           Calls pipeline.ingest_directory() for each watched directory.
           This catches files that were missed (watcher restart, etc.)

  def create_scheduler(config, pipeline, watcher) -> AsyncIOScheduler: ...

No tests needed for the watcher (integration-level, hard to unit test).
Add a note in the test file explaining this.
```

---

## Phase 9 — FastAPI server

**Goal:** HTTP layer exposing search, chat, indexing, and file browsing.
The UI is a single HTML file using HTMX — no build step required.

**Prompt for Claude Code:**
```
Read CLAUDE.md, @server/main.py (create it), @server/schemas.py,
and each routes file.

Step 1 — server/schemas.py: Pydantic v2 models for all requests/responses.

  SearchRequest: query (str), top_k (int=10), filetype (str|None),
                 path_prefix (str|None)
  SearchResult: file_path, filename, filetype, score (float), snippet (str),
                modified_at (str)
  SearchResponse: results (list[SearchResult]), query (str), took_ms (float)

  ChatRequest: message (str), history (list[dict]=[] ), top_k (int=5)
  (chat response is SSE stream, no response schema needed)

  IndexRequest: path (str)
  IndexResponse: status (str), chunks (int), error (str="")

  FileRecord: path, filetype, size_bytes, indexed_at, status, chunk_count

Step 2 — server/routes/search.py:
  GET /search?q=...&top_k=10&filetype=pdf&path_prefix=/work
  1. Embed the query using the embedder.
  2. Build sparse vector for the query.
  3. Build Qdrant filter from filetype/path_prefix if provided.
  4. Call vector_store.search(dense, sparse, top_k, filters).
  5. Return SearchResponse. Snippet = first 200 chars of chunk payload text.

Step 3 — server/routes/chat.py:
  POST /chat (JSON body: ChatRequest)
  Returns SSE stream (text/event-stream).
  1. Embed the user message.
  2. Retrieve top_k chunks from vector store.
  3. Build a system prompt:
       "You are a file assistant. Answer based only on the provided context.
        If the answer is not in the context, say so.
        For each fact, cite the source file path."
  4. Stream response from LLM API (Anthropic or Ollama based on config).
  5. Yield SSE events: data: {"token": "..."} then data: {"done": true}.

Step 4 — server/routes/index.py:
  POST /index  body: {"path": "/absolute/path"}  → triggers pipeline.ingest()
  DELETE /index body: {"path": "..."}            → triggers pipeline.delete()

Step 5 — server/routes/files.py:
  GET /files?limit=50&offset=0&filetype=pdf  → paged list of indexed files

Step 6 — server/main.py:
  FastAPI app factory with lifespan context manager.
  On startup: initialise stores, embedder, pipeline, watcher, scheduler.
  Mount static files for /static (serving index.html).
  Include all routers.
  Expose GET /health → {"status": "ok", "indexed_files": N, "qdrant": "ok"}.

Step 7 — server/static/index.html:
  Single-file HTMX UI. No build step. Features:
  - Search bar at top. On submit: GET /search, render results as cards.
    Each card shows: filename, path, filetype badge, score bar, snippet.
  - "Chat" tab: text input, sends POST /chat, streams response via
    EventSource, renders markdown (use marked.js from CDN).
  - "Files" tab: paged table of all indexed files with status badges.
  - "Re-index" button per file card that calls POST /index.
  Use Tailwind CSS (CDN), HTMX (CDN), marked.js (CDN).
  Dark-mode friendly. No framework — vanilla HTMX only.

Write tests in tests/test_api.py using FastAPI TestClient.
Test: /health returns 200, /search returns results, /index triggers pipeline.
Use mocked pipeline and stores — do not require a running Qdrant in tests.
Run pytest after. Fix any failures.
```

---

## Phase 10 — Integration, scripts, README

**Goal:** Wire everything together, write the setup script, and document it.

**Prompt for Claude Code:**
```
Read CLAUDE.md and the full repo structure.

Step 1 — scripts/setup_qdrant.sh:
  Docker run command for Qdrant with:
  - Port 6333 exposed
  - Named volume for persistence
  - Restart policy: unless-stopped
  - Memory limit flag (e.g. --memory=512m)

Step 2 — scripts/reindex_all.py:
  CLI script that loads config, initialises the pipeline, and calls
  ingest_directory() for each watched_dir in config. Prints progress.
  Usage: python scripts/reindex_all.py [--config path/to/config.yaml]

Step 3 — README.md: Cover:
  - What it does (2 sentences)
  - Requirements: Python 3.11+, Docker, ffmpeg (for video), Tesseract
  - Quick start (copy config, start Qdrant, pip install, uvicorn, open browser)
  - Config reference (brief description of each config.yaml field)
  - Architecture overview (text, no diagram needed)
  - How to add a new file type (point to base.py and registry.py)
  - How to swap the embedding backend

Step 4 — Final check:
  Run the full test suite: pytest tests/ -v --cov=ingester --cov=server
  Fix any remaining failures.
  Run ruff check . and fix all linting errors.
  Run mypy ingester/ server/ and fix all type errors.
```

---

## Suggested session order

Work one phase per session. Each session should end with passing tests.

| Session | Phase | Approximate time |
|---------|-------|-----------------|
| 1 | Phase 1 — Scaffold + config | 15 min |
| 2 | Phase 2 — SQLite metadata store | 20 min |
| 3 | Phase 3 — All parsers | 30 min |
| 4 | Phase 4 — Chunker | 15 min |
| 5 | Phase 5 — Embedders | 20 min |
| 6 | Phase 6 — Qdrant vector store | 25 min |
| 7 | Phase 7 — Pipeline | 20 min |
| 8 | Phase 8 — Watcher + scheduler | 15 min |
| 9 | Phase 9 — FastAPI + UI | 45 min |
| 10 | Phase 10 — Integration + docs | 20 min |

---

## Debugging tips for Claude Code sessions

**If Claude starts implementing before you approve the plan:**
Press Escape, then type: "Stop. Enter Plan Mode first. Show me the plan."

**If a session goes off-track:**
`/clear` and restart with a focused single-task prompt referencing
specific files with `@path`.

**If tests keep failing:**
"Do not add new code. Read the failing test output carefully and fix only
the specific failure. Show me your reasoning before changing anything."

**If Claude modifies files it shouldn't:**
Use `/permissions` to restrict which directories Claude can write to during
sensitive phases (e.g., lock it to `ingester/store/` during Phase 2).

**Context tip:** Claude Code's context auto-compacts in long sessions.
If you notice it forgetting earlier decisions, `/clear` and re-anchor
with: "Read CLAUDE.md and @[relevant files]. Continue from where we left off: [brief state summary]."
