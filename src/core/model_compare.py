"""
MeshCtx Multi-Model Compare — Side-by-Side Model Comparison
=============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Concurrent multi-model chat comparison with streaming support.

License: AGPLv3 for non-commercial use only.
"""
import asyncio
import json
import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


async def compare_models(message: str, model_ids: List[str],
                         temperature: float = 0.7, max_tokens: int = 2048) -> Dict[str, Any]:
    """
    Send the same message to multiple models concurrently.

    Args:
        message: User message
        model_ids: List of model IDs (e.g., ["deepseek:chat", "openai:gpt-4o"])
        temperature: Generation temperature
        max_tokens: Max tokens per model

    Returns:
        {results: [{model, content, tokens, latency_ms, error?}], total_ms}
    """
    if not model_ids:
        return {"results": [], "total_ms": 0}

    from src.model_registry import get_registry

    async def call_one(model_id: str) -> Dict:
        t0 = time.time()
        try:
            reg = get_registry()
            client = reg.get(model_id)
            if not client:
                return {"model": model_id, "content": f"[未配置 {model_id}]",
                        "tokens": 0, "latency_ms": 0, "error": "not_configured"}

            resp = client.chat([{"role": "user", "content": message}],
                               temperature=temperature, max_tokens=max_tokens)
            latency = round((time.time() - t0) * 1000)
            return {
                "model": model_id,
                "content": resp.get("content", ""),
                "tokens": resp.get("tokens", 0),
                "latency_ms": latency,
                "actual_model": resp.get("model", model_id),
            }
        except Exception as e:
            return {"model": model_id, "content": f"[错误: {e}]",
                    "tokens": 0, "latency_ms": round((time.time() - t0) * 1000),
                    "error": str(e)}

    t_start = time.time()
    tasks = [call_one(mid) for mid in model_ids[:5]]  # Max 5 concurrent
    results = await asyncio.gather(*tasks)
    total_ms = round((time.time() - t_start) * 1000)

    return {"results": results, "total_ms": total_ms}


async def compare_models_stream(message: str, model_ids: List[str]):
    """
    SSE generator for streaming multi-model comparison.
    Yields: data: {type: "start"|"token"|"done", model: str, content?: str}
    """
    from src.model_registry import get_registry

    yield f"data: {json.dumps({'type': 'start', 'models': model_ids[:5]})}\n\n"

    async def stream_one(model_id: str):
        yield f"data: {json.dumps({'type': 'model_start', 'model': model_id})}\n\n"
        try:
            reg = get_registry()
            client = reg.get(model_id)
            if not client:
                yield f"data: {json.dumps({'type': 'token', 'model': model_id, 'content': f'[未配置]'})}\n\n"
                yield f"data: {json.dumps({'type': 'model_done', 'model': model_id})}\n\n"
                return

            t0 = time.time()
            full = ""
            for chunk in client.chat_stream([{"role": "user", "content": message}]):
                full += chunk
                yield f"data: {json.dumps({'type': 'token', 'model': model_id, 'content': chunk})}\n\n"

            latency = round((time.time() - t0) * 1000)
            yield f"data: {json.dumps({'type': 'model_done', 'model': model_id, 'latency_ms': latency, 'tokens': len(full.split())})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'token', 'model': model_id, 'content': f'[错误: {e}]'})}\n\n"
            yield f"data: {json.dumps({'type': 'model_done', 'model': model_id})}\n\n"

    # Stream all models concurrently via queue
    queue = asyncio.Queue()

    async def producer(mid):
        async for data in stream_one(mid):
            await queue.put(data)

    producers = [asyncio.create_task(producer(mid)) for mid in model_ids[:3]]
    done_count = 0

    while done_count < len(producers):
        try:
            data = await asyncio.wait_for(queue.get(), timeout=120)
            yield data
            if '"model_done"' in data:
                done_count += 1
        except asyncio.TimeoutError:
            break

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
