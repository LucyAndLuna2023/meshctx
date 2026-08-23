#!/usr/bin/env bash
# 闭源核心叠加器 — 三平台 CI 共用 (build-linux/macos 调用的 bash 版; windows 有同逻辑 pwsh 版)
#
# 修复(2026-08-24, 006 Mac): 私有 meshctx-core 是「真身模块 + 全量镜像」, 旧逻辑用 tar 整体覆盖
# src/core/, 导致私有仓里陈旧的 auth_v2.py 覆盖公开仓已修复版本 → 发布包认证默认开启且无密码,
# /api/* 全 401, UI 聊天/保存 token 不可用 (CLI 正常)。本脚本只叠加:
#   ① 公开仓缺失的闭源独有模块 (desktop_tool / lsp_tool / mcp_gateway / obs_integration /
#      patch_generator / ppt_generator / spreadsheet_tool 等护城河)
#   ② 公开仓为 stub 的文件 (crypto / sandbox / kernel / heartbeat 等, 需私有真身)
# 公开仓真实实现 (auth_v2 / cognitive_loop / brain_* 等) 一律保留开源版本, 不被私有镜像覆盖。
set -euo pipefail

CORE_SRC="${1:-/tmp/meshctx-core/src/core}"
[ -d "$CORE_SRC" ] || { echo "FAIL: core 源目录不存在: $CORE_SRC"; exit 1; }

ADDED=0
REPLACED=0
KEPT=0
while IFS= read -r f; do
  f="${f#./}"
  [ -z "$f" ] && continue
  if [ ! -f "src/core/$f" ]; then
    mkdir -p "$(dirname "src/core/$f")"
    cp "$CORE_SRC/$f" "src/core/$f"
    ADDED=$((ADDED+1))
  elif grep -q -e '本文件为 meshctx 开源接口 stub' \
               -e 'meshctx-core required (private repo)' \
               -e 'class _MeshCtxStubProxy' \
               -e '_StubProxy' \
               -e 'meshctx-core (private) NOT installed' "src/core/$f" 2>/dev/null; then
    cp "$CORE_SRC/$f" "src/core/$f"
    REPLACED=$((REPLACED+1))
  else
    KEPT=$((KEPT+1))
    echo "keep public(real): $f"
  fi
done < <(cd "$CORE_SRC" && find . -name '*.py' ! -path './__init__.py' | sort)
echo "core overlay: added=$ADDED replaced_stub=$REPLACED kept_public=$KEPT"

# 门禁: 公开仓已修复的 auth_v2(回环信任) 必须保留在包内 — 回归保护
if grep -q "_is_loopback_client" src/core/auth_v2.py 2>/dev/null; then
  echo "OK: public auth_v2 preserved (loopback trust)"
else
  echo "FAIL: auth_v2 被私有镜像覆盖, 回环信任丢失 — 禁止发布"
  exit 1
fi
# 门禁: crypto 必须是私有真身 (stub 会破坏 key 加密)
if grep -q -e '_MeshCtxStubProxy' -e 'meshctx-core required (private repo)' src/core/crypto.py 2>/dev/null; then
  echo "FAIL: crypto.py 仍为 stub — 闭源核心未落地"
  exit 1
fi

test -f src/core/desktop_tool.py && echo "OK: closed-source core bundled" || { echo "FAIL: core copy missing"; exit 1; }
