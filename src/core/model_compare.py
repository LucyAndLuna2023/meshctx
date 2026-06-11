"""Model Compare — 开源版 (stub)"""
import asyncio

async def compare_models(*a, **kw) -> dict:
    return {"winner": "", "scores": {}, "error": "Model comparison requires meshctx-core"}

async def compare_models_stream(*a, **kw):
    yield {"status": "stub", "message": "install meshctx-core"}
