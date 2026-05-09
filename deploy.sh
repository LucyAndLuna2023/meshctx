#!/bin/bash
# ============================================================
# meshctx 远程部署脚本
# 目标服务器: 47.120.0.239 (备用阿里云)
# 端口: 8000
# ============================================================
set -e

SERVER="47.120.0.239"
REMOTE_USER="root"
REMOTE_DIR="/opt/meshctx"
PASSWORD="LucyAndLuna@20230609"
LOCAL_DIR="/mnt/e/BaiduSyncdisk/Jason/personal/meshctx"

echo "========================================"
echo " meshctx 部署脚本 v0.2.0"
echo " 目标: ${REMOTE_USER}@${SERVER}:${REMOTE_DIR}"
echo "========================================"

# 1. 打包项目（排除venv等大文件）
echo "[1/5] 打包项目..."
cd "${LOCAL_DIR}"
tar --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='node_modules' --exclude='data' \
    --exclude='logs' -czf /tmp/meshctx_deploy.tar.gz .

echo "[2/5] 上传到服务器..."
sshpass -p "${PASSWORD}" scp -o StrictHostKeyChecking=no \
    /tmp/meshctx_deploy.tar.gz ${REMOTE_USER}@${SERVER}:/tmp/

echo "[3/5] 远程解压 & 安装依赖..."
sshpass -p "${PASSWORD}" ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${SERVER} << 'REMOTE_SCRIPT'
    set -e
    mkdir -p /opt/meshctx
    cd /opt/meshctx

    # 解压
    tar -xzf /tmp/meshctx_deploy.tar.gz -C /opt/meshctx/
    rm /tmp/meshctx_deploy.tar.gz

    # 安装Python依赖
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    ./venv/bin/pip install -q -r requirements.txt

    # 创建数据目录
    mkdir -p data/vectors logs

    echo "依赖安装完成"
REMOTE_SCRIPT

echo "[4/5] 停止旧服务..."
sshpass -p "${PASSWORD}" ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${SERVER} \
    "fuser -k 8000/tcp 2>/dev/null || true; sleep 1"

echo "[5/5] 启动新服务..."
sshpass -p "${PASSWORD}" ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${SERVER} << 'REMOTE_START'
    cd /opt/meshctx
    nohup ./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 \
        > logs/server.log 2>&1 &
    sleep 2

    # 验证
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "=== 部署成功 ==="
        curl -s http://localhost:8000/health | python3 -m json.tool
    else
        echo "=== 部署失败，检查日志 ==="
        tail -20 logs/server.log
        exit 1
    fi
REMOTE_START

echo ""
echo "========================================"
echo " meshctx 部署完成!"
echo " API: http://${SERVER}:8000"
echo " WebUI: http://${SERVER}:8000/ui"
echo " Health: http://${SERVER}:8000/health"
echo " Docs: http://${SERVER}:8000/docs"
echo "========================================"

# 清理本地临时文件
rm -f /tmp/meshctx_deploy.tar.gz
