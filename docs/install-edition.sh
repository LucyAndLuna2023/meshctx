#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx Edition Installer v2 — Personal / Team / Enterprise
# Usage:
#   personal:   curl -fsSL .../install-edition.sh | bash -s -- personal
#   team:       curl -fsSL .../install-edition.sh | bash -s -- team
#   enterprise: curl -fsSL .../install-edition.sh | bash -s -- enterprise
# Requires: MESHCTX_GIT_TOKEN for team/enterprise (GitHub token, scope: repo)
# ═══════════════════════════════════════════════════════
set -e
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

EDITION="${1:-personal}"
VERSION="3.121.7"
INSTALL_DIR="${MESHCTX_HOME:-$HOME/.meshctx}"

case "$EDITION" in
  personal)
    EDITION_LABEL="Personal (free)"
    REPOS="meshctx"
    ;;
  team)
    EDITION_LABEL="Team (\$9/人/月)"
    REPOS="meshctx meshctx-team"
    ;;
  enterprise)
    EDITION_LABEL="Enterprise (\$29/人/月)"
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
echo "[1/3] 下载基础版 (meshctx)..."
if ! git clone --depth 1 --branch "v${VERSION}" https://github.com/LucyAndLuna2023/meshctx.git "$INSTALL_DIR/src/meshctx" 2>/dev/null; then
  git clone --depth 1 https://github.com/LucyAndLuna2023/meshctx.git "$INSTALL_DIR/src/meshctx" 2>/dev/null
fi

# 2. 附加私有库 (团队/企业版需 token)
if [ "$EDITION" != "personal" ]; then
  if [ -z "$MESHCTX_GIT_TOKEN" ]; then
    echo -e "${RED}[ERROR] 团队/企业版需要 MESHCTX_GIT_TOKEN (GitHub token, scope: repo)${NC}"
    echo "获取: https://github.com/settings/tokens"
    exit 1
  fi
  echo "[2/3] 下载私有库..."
  for repo in $REPOS; do
    [ "$repo" = "meshctx" ] && continue
    if [ -d "$INSTALL_DIR/src/${repo}" ]; then
      # P3-2 (002codex): 已存在时 git pull 更新 + 重新去 token (防旧 token 残留)
      echo "  ${repo}: 已存在, 更新中..."
      git -C "$INSTALL_DIR/src/${repo}" pull --ff-only 2>/dev/null || true
      git -C "$INSTALL_DIR/src/${repo}" remote set-url origin "https://github.com/LucyAndLuna2023/${repo}.git" 2>/dev/null
      continue
    fi
    echo "  下载 ${repo} (私有)..."
    if ! git clone --depth 1 "https://${MESHCTX_GIT_TOKEN}@github.com/LucyAndLuna2023/${repo}.git" \
        "$INSTALL_DIR/src/${repo}" 2>/dev/null; then
      echo -e "${RED}  clone 失败 ${repo} (检查 token/网络)${NC}"
      exit 1
    fi
    # P1 (002codex/002meshctx 审计): token 泄漏修复 — clone 后从 remote URL 移除 token
    git -C "$INSTALL_DIR/src/${repo}" remote set-url origin "https://github.com/LucyAndLuna2023/${repo}.git" 2>/dev/null
    echo "    token 已从 remote 移除 (防 .git/config 落盘)"
  done

  echo "[2b] 合并私有模块到 src (P2-3: 已存在非-stub 模块跳过, 防漂移覆盖)..."
  for _f in "$INSTALL_DIR/src"/meshctx-*/src/core/*.py; do
    [ -f "$_f" ] || continue
    _base=$(basename "$_f")
    _dst="$INSTALL_DIR/src/meshctx/src/core/$_base"
    if [ ! -f "$_dst" ] || grep -q "_IMPLEMENTATION_MOVED" "$_dst" 2>/dev/null; then
      cp "$_f" "$_dst" 2>/dev/null || true
    fi
  done
  for _f in "$INSTALL_DIR/src"/meshctx-*/src/web_crews.py; do
    [ -f "$_f" ] && cp "$_f" "$INSTALL_DIR/src/meshctx/src/" 2>/dev/null || true
  done
fi

# 3. Post-check (meshctx 审计建议): 验证 edition 检测正确, 防付费用户静默降级
echo "[3/3] 验证 edition 检测..."
cd "$INSTALL_DIR/src/meshctx" 2>/dev/null || { echo -e "${RED}安装目录异常${NC}"; exit 1; }
_DETECTED=""
if command -v python3 >/dev/null 2>&1; then
  _DETECTED=$(python3 -c "from src.core._edition import detect_edition; print(detect_edition())" 2>/dev/null || echo "unknown")
else
  _DETECTED="unknown (无 python3)"
fi
echo "  预期: $EDITION | 实际: $_DETECTED"

case "$EDITION" in
  personal)
    # P2 (002meshctx 审计): personal 也 fail-closed — 若意外检测到付费功能,
    # 报错退出 (防免费版意外解锁付费墙, 与 team/enterprise 一致)
    if [ "$_DETECTED" != "personal" ]; then
      echo -e "${RED}  ❌ 检测到 $_DETECTED (预期 personal) — 免费版不应包含付费功能!${NC}"
      echo -e "${RED}  请检查是否有 meshctx-team/enterprise 残留合并${NC}"
      exit 1
    fi
    echo -e "${GREEN}  ✅ personal 版检测正确${NC}"
    ;;
  team)
    if [ "$_DETECTED" = "team" ] || [ "$_DETECTED" = "enterprise" ]; then
      echo -e "${GREEN}  ✅ team 版检测正确 (实际 $_DETECTED ≥ team)${NC}"
    else
      echo -e "${RED}  ❌ 检测到 $_DETECTED (预期 ≥team) — 付费用户静默降级! 请检查私有库合并${NC}"
      exit 1
    fi
    ;;
  enterprise)
    if [ "$_DETECTED" = "enterprise" ]; then
      echo -e "${GREEN}  ✅ enterprise 版检测正确${NC}"
    else
      echo -e "${RED}  ❌ 检测到 $_DETECTED (预期 enterprise) — 企业功能缺失! 请检查私有库合并${NC}"
      exit 1
    fi
    ;;
esac

echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e "${GREEN}✅ meshctx ${EDITION_LABEL} v${VERSION} 安装完成${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo "运行: cd $INSTALL_DIR/src/meshctx && python3 -m uvicorn src.main:app --port 3001"
echo "验证: cd $INSTALL_DIR/src/meshctx && python3 -c 'from src.core._edition import detect_edition; print(detect_edition())'"
