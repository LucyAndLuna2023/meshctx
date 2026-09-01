#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx Edition Installer — Personal / Team / Enterprise
# Usage:
#   personal: curl -fsSL .../install-edition.sh | bash -s -- personal
#   team:     curl -fsSL .../install-edition.sh | bash -s -- team
#   enterp:   curl -fsSL .../install-edition.sh | bash -s -- enterprise
# ═══════════════════════════════════════════════════════
set -e
GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

EDITION="${1:-personal}"
VERSION="3.121.7"
INSTALL_DIR="${MESHCTX_HOME:-$HOME/.meshctx}"

case "$EDITION" in
  personal)
    EDITION_LABEL="Personal (free)"
    REPOS="meshctx"
    ;;
  team)
    EDITION_LABEL="Team ($9/人/月)"
    REPOS="meshctx meshctx-team"
    ;;
  enterprise)
    EDITION_LABEL="Enterprise ($29/人/月)"
    REPOS="meshctx meshctx-enterprise meshctx-team"  # enterprise 先合并, 防 team 版先占位同名模块
    ;;
  *)
    echo "Unknown edition: $EDITION (use personal|team|enterprise)"
    exit 1
    ;;
esac

echo -e "${GREEN}meshctx ${EDITION_LABEL} 安装器 v${VERSION}${NC}"
echo "版本: $EDITION | 仓库: $REPOS"

mkdir -p "$INSTALL_DIR/src"

# 1. 基础个人版 (开源)
echo "下载基础版 (meshctx)..."
git clone --depth 1 --branch "v${VERSION}" https://github.com/LucyAndLuna2023/meshctx.git "$INSTALL_DIR/src/meshctx" 2>/dev/null \
  || git clone --depth 1 https://github.com/LucyAndLuna2023/meshctx.git "$INSTALL_DIR/src/meshctx" 2>/dev/null

# 2. 附加私有库 (团队/企业版需 token)
if [ "$EDITION" != "personal" ]; then
  if [ -n "$MESHCTX_GIT_TOKEN" ]; then
    for repo in $REPOS; do
      [ "$repo" = "meshctx" ] && continue
      echo "下载 $repo (私有)..."
      git clone --depth 1 "https://${MESHCTX_GIT_TOKEN}@github.com/LucyAndLuna2023/${repo}.git" \
        "$INSTALL_DIR/src/${repo}" 2>/dev/null || {
        echo "clone 失败 $repo"; exit 1; }
      # P1 (002codex/002meshctx 审计): token 泄漏修复 — clone 后从 remote URL 移除 token
      git -C "$INSTALL_DIR/src/${repo}" remote set-url origin "https://github.com/LucyAndLuna2023/${repo}.git" 2>/dev/null
      echo "  $repo: token 已从 remote 移除 (防 .git/config 落盘)"
      {
        echo -e "${RED}需要 MESHCTX_GIT_TOKEN 访问私有库 $repo${NC}"
        echo "获取: https://github.com/settings/tokens (read:packages)"
        exit 1
      }
    done
    # 合并私有模块到 src (P2-3: 共享模块已存在则跳过, 防三库版本漂移覆盖)
    for _f in "$INSTALL_DIR/src"/meshctx-*/src/core/*.py; do
      _base=$(basename "$_f")
      _dst="$INSTALL_DIR/src/meshctx/src/core/$_base"
      if [ ! -f "$_dst" ] || grep -q "_IMPLEMENTATION_MOVED" "$_dst" 2>/dev/null; then
        cp "$_f" "$_dst" 2>/dev/null || true
      fi
    done
    for _f in "$INSTALL_DIR/src"/meshctx-*/src/web_crews.py; do
      [ -f "$_f" ] && cp "$_f" "$INSTALL_DIR/src/meshctx/src/" 2>/dev/null || true
    done
  else
    echo -e "${RED}团队/企业版需要 MESHCTX_GIT_TOKEN (GitHub token 访问私有库)${NC}"
    exit 1
  fi
fi

echo -e "${GREEN}✅ meshctx ${EDITION_LABEL} v${VERSION} 安装完成${NC}"
echo "运行: cd $INSTALL_DIR/src/meshctx && python3 -m uvicorn src.main:app --port 3001"
