#!/bin/bash
# ============================================================
# meshctx 快速本地启动脚本
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    ./venv/bin/pip install -q -r requirements.txt
fi

# 创建必要目录
mkdir -p data/vectors logs

echo "========================================"
echo " meshctx 本地启动"
echo " API: http://localhost:8000"
echo " WebUI: http://localhost:8000/ui"
echo " Docs: http://localhost:8000/docs"
echo "========================================"

# 启动服务
./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
