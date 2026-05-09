#!/bin/bash
# ============================================================
# meshctx v1.0 远程部署脚本
# 目标服务器: 47.120.0.239 (备用阿里云)
# 端口: 8000
# ============================================================
set -e

SERVER="47.120.0.239"
REMOTE_USER="root"
REMOTE_DIR="/opt/meshctx"
PASSWORD="LucyAndLuna@20230609"
LOCAL_DIR="/home/administrator/meshctx-local"

echo "========================================"
echo " meshctx v1.0 部署脚本"
echo " 目标: ${REMOTE_USER}@${SERVER}:${REMOTE_DIR}"
echo "========================================"

# 1. 打包项目
echo "[1/5] 打包项目..."
cd "${LOCAL_DIR}"
tar --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='node_modules' --exclude='data' \
    --exclude='logs' --exclude='.pytest_cache' \
    -czf /tmp/meshctx_deploy.tar.gz .

echo "[2/5] 上传到服务器..."
sshpass -p "${PASSWORD}" scp -o StrictHostKeyChecking=no \
    /tmp/meshctx_deploy.tar.gz ${REMOTE_USER}@${SERVER}:/tmp/

echo "[3/5] 远程解压 & 安装依赖..."
sshpass -p "${PASSWORD}" ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${SERVER} << 'REMOTE_SCRIPT'
    set -e
    mkdir -p /opt/meshctx
    cd /opt/meshctx

    tar -xzf /tmp/meshctx_deploy.tar.gz -C /opt/meshctx/
    rm /tmp/meshctx_deploy.tar.gz

    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    ./venv/bin/pip install -q -r requirements.txt
    ./venv/bin/pip install -q pytest-asyncio 2>/dev/null || true

    mkdir -p data logs
    echo "依赖安装完成"
REMOTE_SCRIPT

echo "[4/5] 停止旧服务..."
sshpass -p "${PASSWORD}" ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${SERVER} \
    "fuser -k 8000/tcp 2>/dev/null || true; sleep 1"

echo "[5/5] 启动 meshctx v1.0..."
sshpass -p "${PASSWORD}" ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${SERVER} << 'REMOTE_START'
    cd /opt/meshctx
    nohup ./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 \
        > logs/server.log 2>&1 &
    sleep 3

    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "=== meshctx v1.0 部署成功 ==="
        curl -s http://localhost:8000/health
    else
        echo "=== 启动失败，检查日志 ==="
        tail -30 logs/server.log
        exit 1
    fi
REMOTE_START

echo ""
echo "========================================"
echo " meshctx v1.0 部署完成!"
echo " API: http://${SERVER}:8000"
echo " WebUI: http://${SERVER}:8000/ui"
echo " Health: http://${SERVER}:8000/health"
echo " Docs: http://${SERVER}:8000/docs"
echo " Kernel: http://${SERVER}:8000/kernel/stats"
echo "========================================"

rm -f /tmp/meshctx_deploy.tar.gz
