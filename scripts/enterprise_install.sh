#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# MeshCtx Enterprise 私有化部署 — 内网/离线环境一键安装
# (2026-08-28, BP Enterprise 功能: private_deploy)
#
# 用法:
#   ./enterprise_install.sh              # 在线安装 (Docker 或源码)
#   ./enterprise_install.sh --offline    # 离线安装 (需离线包目录)
#   ./enterprise_install.sh --docker     # Docker 部署
#   ./enterprise_install.sh --status     # 健康检查
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

PORT="${MESHCTX_PORT:-3001}"
DATA_DIR="${MESHCTX_DATA:-$HOME/.meshctx}"
MODE="${1:-}"

echo "═══ MeshCtx Enterprise 私有化部署 ═══"
echo "端口: $PORT | 数据: $DATA_DIR | 模式: ${MODE:-auto}"

mkdir -p "$DATA_DIR"

case "$MODE" in
  --docker)
    echo "[1/3] Docker 部署..."
    if command -v docker >/dev/null 2>&1; then
      docker build -t meshctx .
      docker run -d --name meshctx -p "$PORT:$PORT" \
        -v "$DATA_DIR:/root/.meshctx" \
        --restart unless-stopped meshctx
      echo "[2/3] 容器已启动 (端口 $PORT)"
    else
      echo "⚠ Docker 不可用, 回退源码部署"; exec "$0"
    fi
    ;;

  --offline)
    echo "[1/3] 离线安装 (需离线包: wheelhouse/ + requirements.txt)"
    OFFLINE_DIR="${OFFLINE_DIR:-wheelhouse}"
    if [ ! -d "$OFFLINE_DIR" ]; then
      echo "❌ 离线包目录 $OFFLINE_DIR 不存在"; exit 1
    fi
    python3 -m venv "$DATA_DIR/venv"
    "$DATA_DIR/venv/bin/pip" install --no-index \
      --find-links "$OFFLINE_DIR" -r requirements.txt
    echo "[2/3] 依赖已从离线包安装"
    # 离线启动
    "$DATA_DIR/venv/bin/python" -m src.main & 
    echo "[3/3] 已启动 (内网/离线环境)"
    ;;

  --status)
    echo "═══ 健康检查 ═══"
    curl -sf "http://127.0.0.1:$PORT/health" && echo "✅ 服务正常 (端口 $PORT)" \
      || echo "❌ 服务未响应 (端口 $PORT)"
    echo "── 容器状态 ──"
    docker ps 2>/dev/null | grep meshctx || echo "无 meshctx 容器"
    echo "── systemd ──"
    systemctl status meshctx 2>/dev/null | head -3 || echo "未注册 systemd"
    exit 0
    ;;

  --systemd)
    echo "[1/3] 注册 systemd 服务 (开机自启 + 崩溃重启)"
    cat > /etc/systemd/system/meshctx.service << SERVICE
[Unit]
Description=MeshCtx Enterprise
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$(pwd)
Environment=PORT=$PORT
Environment=MESHCTX_DATA=$DATA_DIR
ExecStart=$(which python3) -m src.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
    systemctl daemon-reload
    systemctl enable meshctx
    systemctl start meshctx
    echo "[2/3] systemd 已注册并启动"
    ;;
esac

echo "═══ 部署完成 ═══"
echo "访问: http://<内网IP>:$PORT/ui"
echo "数据目录: $DATA_DIR"
echo "健康检查: curl http://127.0.0.1:$PORT/health"
