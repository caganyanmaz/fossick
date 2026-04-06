# fossick

Fossick is a local semantic search engine that watches your directories, indexes every file it understands (documents, code, spreadsheets, images, video), and lets you search or chat with the contents through a web UI.

## Requirements

- Python 3.11+
- Docker (for Qdrant vector store)
- `ffmpeg` (optional — required for video file transcription)
- Tesseract (optional — required for OCR on scanned PDFs and images)

## Quick start

```bash
# 1. Copy and edit the config
cp config.example.yaml config.yaml
$EDITOR config.yaml           # set watched_dirs and API keys as needed

# 2. Start Qdrant
bash scripts/setup_qdrant.sh

# 3. Install the package
pip install -e ".[dev]"

# 4. Run the server
uvicorn server.main:app --reload --port 8000

# 5. Open the UI
# http://localhost:8000
```

To do a one-shot full reindex (useful after adding new directories):

```bash
python scripts/reindex_all.py --config config.yaml
```

## Config reference

| Field | Description |
|-------|-------------|
| `watched_dirs` | List of absolute directory paths to monitor and index |
| `qdrant.host` / `.port` | Qdrant server address (default: localhost:6333) |
| `qdrant.collection` | Qdrant collection name |
| `qdrant.on_disk_vectors` | Store vectors on disk to reduce RAM usage |
| `qdrant.quantization` | `scalar_int8` — 4× less RAM, ~2% quality loss |
| `sqlite.path` | Path to the SQLite index database |
| `embedding.backend` | `local` (sentence-transformers) or `api` (OpenAI / Voyage AI) |
| `embedding.local.model` | Model name, e.g. `all-MiniLM-L6-v2` or `nomic-ai/nomic-embed-text-v1.5` |
| `embedding.local.batch_size` | Batch size for CPU inference (max 32) |
| `embedding.api.provider` | `openai` or `voyageai` |
| `embedding.api.model` | API model name |
| `embedding.api.api_key` | API key (or set `EMBEDDING_API_KEY` env var) |
| `llm.backend` | `api` (Anthropic / OpenAI) or `local` (Ollama) |
| `llm.api.provider` | `anthropic` or `openai` |
| `llm.api.model` | LLM model name |
| `llm.api.api_key` | API key (or set `LLM_API_KEY` env var) |
| `llm.local.model` | Ollama model tag, e.g. `llama3.2:3b` |
| `llm.local.ollama_host` | Ollama server URL |
| `ocr.backend` | `tesseract` (local via Docling) or `api` |
| `video.keyframes` | Number of evenly-spaced frames to extract and caption |
| `video.caption_backend` | `local` (moondream2 via Ollama) or `api` |
| `video.transcription_backend` | `api` (Whisper API) |
| `scheduler.watch_interval_seconds` | How often the watcher loop drains its queue |
| `scheduler.full_rescan_cron` | Cron expression for overnight full rescan |

## Architecture

```
watched_dirs
     │
     ▼
FileWatcher (watchdog)
     │  CREATE / MODIFY events
     ▼
event_queue (asyncio.Queue)
     │
     ▼
APScheduler watch_loop  ──── nightly full_rescan
     │
     ▼
Pipeline.ingest(path)
     │
     ├─► Parser (docling / spreadsheet / code / image / video)
     │       └─► ParsedDocument(text, metadata)
     │
     ├─► Chunker  →  list[Chunk]  (sliding window, code-aware boundaries)
     │
     ├─► Embedder (local sentence-transformers  OR  API)
     │       └─► dense vectors
     │
     ├─► BM25 sparse vectors (built in-process)
     │
     ├─► VectorStore (Qdrant)  ←── hybrid dense+sparse search
     │
     └─► MetadataStore (SQLite)  ←── source of truth, can rebuild Qdrant

FastAPI server
     ├── GET  /search        — hybrid semantic search
     ├── POST /chat          — SSE streaming RAG chat
     ├── POST /index         — manually trigger ingest
     ├── DELETE /index       — remove a file from the index
     ├── GET  /files         — browse indexed files
     └── GET  /health        — liveness check
```

SQLite is the source of truth. Qdrant holds derived embeddings and can be rebuilt from SQLite at any time.

## How to add a new file type

1. Create a new parser in `ingester/parser/` that subclasses `BaseParser` (`ingester/parser/base.py`):

   ```python
   from ingester.parser.base import BaseParser, ParsedDocument

   class MyFormatParser(BaseParser):
       def can_parse(self, path: str) -> bool:
           return path.endswith(".myext")

       def parse(self, path: str) -> ParsedDocument:
           text = ...  # extract text
           return ParsedDocument(text=text, metadata={}, source_path=path)
   ```

2. Register the extension in `ingester/parser/registry.py` by adding it to the extension-to-parser mapping.

## How to swap the embedding backend

Change `embedding.backend` in `config.yaml`:

```yaml
embedding:
  backend: api          # was "local"
  api:
    provider: openai
    model: text-embedding-3-small
    api_key: ""         # or set EMBEDDING_API_KEY env var
```

The `get_embedder()` factory in `ingester/embedder/__init__.py` reads this value and returns the correct implementation. No code changes needed.
