#!/bin/bash
# MeshCtx Web UI 测试启动
cd /home/administrator/meshctx-local
source /home/administrator/meshctx-venv/bin/activate
python3 -c "
import asyncio, uvicorn
from src.memory_engine import MemoryEngine
from src.main import app

async def main():
    engine = MemoryEngine(use_llm=False, use_vector_store=False)
    app.state.memory_engine = engine
    print('MeshCtx Web UI → http://localhost:8000/ui')
    config = uvicorn.Config(app, host='0.0.0.0', port=8000, log_level='info')
    await uvicorn.Server(config).serve()

asyncio.run(main())
"
