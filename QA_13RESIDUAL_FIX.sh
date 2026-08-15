#!/bin/bash
# QA审计: 13脑区残留修复脚本 — 2026-07-16
# 执行后需 git commit && git push origin gh-pages
set -e
cd /home/administrator/meshctx-public

echo "=== 1/4 docs/download.html — benchmark Brain Regions 13→17 ==="
sed -i 's|<td>10</td><td>13</td>|<td>10</td><td>17</td>|' docs/download.html
grep -n 'Brain Regions' docs/download.html

echo "=== 2/4 docs/index.html — ZH hero 13大脑区→14脑区 ==="
sed -i 's|13大脑区仿真|14脑区仿真|' docs/index.html
grep -n '大脑区仿真\|脑区仿真' docs/index.html

echo "=== 3/4 docs/getting-started.html — 全部语言 13→17 ==="
sed -i \
  -e 's|13脑区全脑仿真|14脑区全脑仿真|g' \
  -e 's|13-region full-brain|17-region full-brain|g' \
  -e 's|13 Régions|17 Régions|g' \
  -e 's|13 Regionen|17 Regionen|g' \
  -e 's|13脳領域|17脳領域|g' \
  -e 's|13개 뇌 영역|17개 뇌 영역|g' \
  -e 's|13 regiones|17 regiones|g' \
  docs/getting-started.html
grep -n '13.*brain\|13.*脑\|13.*Région\|13.*Regio\|13.*領域\|13.*영역\|13.*regiones' docs/getting-started.html || echo "  ✅ 全部清除"

echo "=== 4/4 docs/LEGAL.html — 全部语言 13-region→17-region ==="
sed -i \
  -e 's|13-region full-brain|17-region full-brain|g' \
  -e 's|13脑区全脑仿真|14脑区全脑仿真|g' \
  docs/LEGAL.html
grep -n '13-region\|13脑区' docs/LEGAL.html || echo "  ✅ 全部清除"

echo ""
echo "=== ✅ 修复完成。执行以下命令推送: ==="
echo "git add docs/ && git commit -m 'fix: 13→14脑区残留 (docs/download|index|getting-started|LEGAL)' && git push origin gh-pages"
