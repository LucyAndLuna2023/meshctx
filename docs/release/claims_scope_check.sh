#!/usr/bin/env bash
# MeshCtx 营销词超卖扫描 — 机器复验脚本 (claims-scope-20260905.md §3-A)
# 用法: bash docs/release/claims_scope_check.sh [repo]
# 输出: 证据文件 docs/release/copy-scan-<YYYYMMDD>-claims.txt (HEAD 基线 + A1 活跃面 / A2 仓库级)
# 判定: A1 (枚举活跃营销面) 必须 0 命中; A2 (仓库级) 命中须 ⊆ 排除类 (claims-scope §3-A0)
set -u
REPO="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$REPO" || exit 2
HEAD="$(git rev-parse HEAD 2>/dev/null || echo no-git)"
OUT="docs/release/copy-scan-$(date +%Y%m%d)-claims.txt"

# ── 词表 = §1.1 表 + 历轮 (copy-scan v3/v4) 检出词形全集 ──
# 注意: 用营销语境全词形, 不用裸序数 (首个/el primer/primero 等会误报 "首个代码WP/crea el primero")
PAT="World's First|world's first|Worlds First|first self-evolv|self-evolv[a-z]*|Self-Evolv[a-z]*|self-improv[a-z]* agent platform|Self-Improv[a-z]* Agent Platform|most intelligent (agent|system|platform|brain)|most powerful (agent|system|platform)|全球首个|全球第一款|世界第一|世界首个|世界第一款|首款|自我进化|自进化|越用越聪明|越来越聪明|最聪明的|最强大的|世界初|世界で初めて|世界で最初|自己進化|自己改善型|自己改善|最も賢い|세계 최초|세계최초|자가 진화|자가진화|자기 진화|자기진화|auto-evolutivo|Auto-Evolutivo|auto-évolutif|Auto-évolutif|El Primer Sistema de Agentes|le premier au monde|premier système au monde|weltweit erste|weltweit erstes|selbstverbessernd|selbstlernend|саморазвивающ|самообучающ|самый умный|ذاتي التحسين|التطور الذاتي"

# ── A1: 枚举活跃营销面 (新增公开页须同步加入) ──
SURFACES="docs/index.html docs/i18n/landing.json docs/download.html docs/getting-started.html docs/governance.html docs/telemetry.html docs/LEGAL.html docs/test-report.html docs/profile.html docs/llms.txt templates/chat.html templates/base.html"

# ── A0 排除类 (内部/审计/历史, 逐类理由见 claims-scope §3-A0) ──
EXCLUDE='docs/marketing/claims-scope-20260905\.md|docs/release/copy-scan-[0-9].*\.txt|docs/marketing/self-evolution-verification-20260903\.md|docs/DESIGN_v1\.0\.md|docs/index\.html\.v2\.14|docs/marketing/MeshCtx_商业计划书_v3\.116\.md|docs/plans/|docs/release/claims_scope_check\.sh|docs/marketing/海外发布内容/'

{
  echo "# claims-scope 扫描证据  $(date -Is)  HEAD=${HEAD}"
  echo "# 词表: ${PAT}"
  echo "## A1 活跃营销面扫描 (期望 0 命中)"
  git -c core.quotepath=false grep -nIE "${PAT}" -- ${SURFACES} 2>/dev/null || echo "A1: 0 hits"
  echo "## A2 仓库级扫描 (docs+templates; 命中须 ∈ 排除类)"
  git -c core.quotepath=false grep -nIE "${PAT}" -- 'docs/*' 'docs/**' 'templates/*' 2>/dev/null \
    | grep -vE "^(${EXCLUDE})" || echo "A2: 0 hits (beyond exclusion classes)"
} > "$OUT"

echo "基线 HEAD: ${HEAD}"
echo "--- A1 (活跃面):"
sed -n '/## A1/,/## A2/p' "$OUT" | grep -vE '^#|^##' | head -20
echo "--- A2 (仓库级, 排除类外):"
sed -n '/## A2/,$p' "$OUT" | grep -vE '^#|^##' | head -20
echo "证据: ${OUT}"
