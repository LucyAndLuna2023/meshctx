#!/bin/bash
# meshctx 每日发布脚本
# 用法: bash scripts/release.sh [patch|minor|major]
# cronjob 每天06:00自动调用此脚本

set -e
cd "$(dirname "$0")/.."

TYPE="${1:-patch}"

echo "=== meshctx release: $TYPE ==="

# 1. 运行测试
echo "[1/5] Running tests..."
python -m pytest tests/ -q --tb=short || { echo "TESTS FAILED"; exit 1; }

# 2. 运行基准
echo "[2/5] Running benchmarks..."
python tests/benchmark_v1.1.py > /tmp/benchmark_latest.txt 2>&1 || true

# 3. 保存基准历史
BENCH_DIR="data/benchmarks"
mkdir -p "$BENCH_DIR"
DATE_TAG=$(date +%Y%m%d_%H%M)
cp /tmp/benchmark_latest.txt "$BENCH_DIR/$DATE_TAG.txt"

# 4. 更新版本号
echo "[3/5] Bumping version..."
CURRENT=$(python -c "from src.core import __version__; print(__version__)" 2>/dev/null || echo "1.1.0")
# Ensure we got a valid version
if [[ ! "$CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    CURRENT="1.1.0"
fi
IFS='.' read -r MAJ MIN PAT <<< "$CURRENT"

case $TYPE in
    major) MAJ=$((MAJ+1)); MIN=0; PAT=0 ;;
    minor) MIN=$((MIN+1)); PAT=0 ;;
    patch) PAT=$((PAT+1)) ;;
esac
NEW_VER="$MAJ.$MIN.$PAT"
echo "  $CURRENT → $NEW_VER"

# 5. 更新版本文件
sed -i "s/__version__ = \"$CURRENT\"/__version__ = \"$NEW_VER\"/" src/core/__init__.py 2>/dev/null || true

# 6. Commit + Tag + Push
echo "[4/5] Committing..."
git add -A
git commit -m "release: v$NEW_VER — daily $TYPE" || echo "  (nothing to commit)"
git tag -a "v$NEW_VER" -m "v$NEW_VER" 2>/dev/null || true

echo "[5/5] Pushing..."
git -c http.proxy=socks5h://127.0.0.1:1081 push origin main --tags 2>&1 || git push origin main --tags 2>&1

echo ""
echo "=== v$NEW_VER released ==="
echo "Benchmarks saved: $BENCH_DIR/$DATE_TAG.txt"
