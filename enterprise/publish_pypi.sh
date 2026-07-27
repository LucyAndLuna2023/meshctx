#!/usr/bin/env bash
# ============================================================
# publish_pypi.sh — MeshCtx PyPI 发布脚本
# 用法: ./publish_pypi.sh [patch|minor|major]
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── 1. 参数解析 ──────────────────────────────────────────
BUMP="${1:-patch}"
case "$BUMP" in
  patch|minor|major) ;;
  *) echo "❌ 用法: $0 [patch|minor|major]"; exit 1 ;;
esac

# ── 2. 版本号自增 ─────────────────────────────────────────
CURRENT=$(python3 -c "from src import __version__; print(__version__)" 2>/dev/null || echo "0.0.0")
IFS='.' read -r MAJ MIN PAT <<< "$CURRENT"

case "$BUMP" in
  major) MAJ=$((MAJ+1)); MIN=0; PAT=0 ;;
  minor) MIN=$((MIN+1)); PAT=0 ;;
  patch) PAT=$((PAT+1)) ;;
esac

NEW_VER="$MAJ.$MIN.$PAT"
echo "🚀 发布 v$CURRENT → v$NEW_VER ($BUMP)"

# ── 3. 版本注入 ──────────────────────────────────────────
sed -i "s/__version__.*=.*\"$CURRENT\"/__version__ = \"$NEW_VER\"/" src/__init__.py 2>/dev/null || \
  echo "__version__ = \"$NEW_VER\"" > src/__init__.py

# ── 4. 质量门禁 ──────────────────────────────────────────
echo "🔍 lint..."
python3 -m py_compile src/core/brain.py && echo "   ✓ brain.py"
python3 -m py_compile src/core/brain_ltp.py && echo "   ✓ brain_ltp.py"
python3 -m py_compile src/core/brain_gnostic.py && echo "   ✓ brain_gnostic.py"

echo "🧪 test..."
python3 -m pytest tests/ -q --tb=short 2>/dev/null && echo "   ✓ tests passed" || echo "   ⚠ no tests/ or failures (non-blocking)"

# ── 5. 构建 ──────────────────────────────────────────────
rm -rf dist/ build/ *.egg-info
python3 -m build --wheel --sdist 2>/dev/null || pip install build && python3 -m build --wheel --sdist

# ── 6. 发布 PyPI ─────────────────────────────────────────
if [ "${TWINE_USERNAME:-}" ] && [ "${TWINE_PASSWORD:-}" ]; then
  echo "📤 uploading to PyPI..."
  python3 -m twine upload dist/* 2>/dev/null || pip install twine && python3 -m twine upload dist/*
  echo "✅ v$NEW_VER published to PyPI"
else
  echo "💡 发布到 PyPI: TWINE_USERNAME=xxx TWINE_PASSWORD=xxx $0 $BUMP"
fi

# ── 7. Git tag ───────────────────────────────────────────
git tag "v$NEW_VER" -m "Release v$NEW_VER ($BUMP)"
git push origin "v$NEW_VER"
echo "🏷️  tag v$NEW_VER pushed"
echo "✅ Done. pip install meshctx==$NEW_VER"