from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from loguru import logger

from ingester.config import AppConfig
from ingester.embedder.base import BaseEmbedder
from ingester.store.vector import VectorStore, _build_sparse_vector
from server.dependencies import get_config, get_embedder, get_vector_store
from server.schemas import ChatRequest

router = APIRouter()

_SYSTEM_PROMPT = (
    "You are a file assistant. Answer based only on the provided context. "
    "If the answer is not in the context, say so. "
    "For each fact, cite the source file path."
)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    config: Annotated[AppConfig, Depends(get_config)],
    embedder: Annotated[BaseEmbedder, Depends(get_embedder)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(body, config, embedder, vector_store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_chat(
    body: ChatRequest,
    config: AppConfig,
    embedder: BaseEmbedder,
    vector_store: VectorStore,
) -> AsyncGenerator[str, None]:
    try:
        loop = asyncio.get_running_loop()
        dense: list[float] = (
            await loop.run_in_executor(None, embedder.embed, [body.message])
        )[0]
        sparse = _build_sparse_vector(body.message)

        chunks = await vector_store.search(dense, sparse, body.top_k)
        context = "\n\n---\n\n".join(
            f"[Source: {r.payload.get('source_path', 'unknown')}]\n{r.payload.get('text', '')}"
            for r in chunks
        )

        if config.llm.backend == "local":
            gen = _stream_ollama(body.message, context, body.history, config)
        else:
            gen = _stream_anthropic(body.message, context, body.history, config)

        async for token_event in gen:
            yield token_event

    except Exception as exc:
        logger.warning("chat stream error: {}", exc)
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    finally:
        yield f"data: {json.dumps({'done': True})}\n\n"


async def _stream_anthropic(
    message: str,
    context: str,
    history: list[dict[str, str]],
    config: AppConfig,
) -> AsyncGenerator[str, None]:
    api_key = config.llm.api.api_key.get_secret_value()
    payload = {
        "model": config.llm.api.model,
        "max_tokens": 1024,
        "system": f"{_SYSTEM_PROMPT}\n\nContext:\n{context}",
        "messages": [*history, {"role": "user", "content": message}],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:") :].strip()
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        token = delta.get("text", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"


async def _stream_ollama(
    message: str,
    context: str,
    history: list[dict[str, str]],
    config: AppConfig,
) -> AsyncGenerator[str, None]:
    payload = {
        "model": config.llm.local.model,
        "messages": [
            {
                "role": "system",
                "content": f"{_SYSTEM_PROMPT}\n\nContext:\n{context}",
            },
            *history,
            {"role": "user", "content": message},
        ],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{config.llm.local.ollama_host}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = event.get("message", {}).get("content", "")
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if event.get("done"):
                    break
