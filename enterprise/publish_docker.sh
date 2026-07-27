#!/usr/bin/env bash
# ============================================================
# publish_docker.sh — MeshCtx Docker 发布脚本
# 用法: ./publish_docker.sh [tag]
# ============================================================
set -euo pipefail

TAG="${1:-latest}"
IMAGE="meshctx/meshctx"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "🐳 Building $IMAGE:$TAG ..."

# ── 1. 构建 ──────────────────────────────────────────────
docker build \
  --tag "$IMAGE:$TAG" \
  --tag "$IMAGE:latest" \
  --build-arg MESHCTX_VERSION="$TAG" \
  --file "$REPO_ROOT/enterprise/Dockerfile" \
  "$REPO_ROOT"

# ── 2. 验证 ──────────────────────────────────────────────
docker run --rm "$IMAGE:$TAG" meshctx --version

# ── 3. 推送 ──────────────────────────────────────────────
if docker info 2>/dev/null | grep -q "Username:"; then
  docker push "$IMAGE:$TAG"
  docker push "$IMAGE:latest"
  echo "✅ $IMAGE:$TAG pushed"
else
  echo "💡 docker login first, then re-run"
fi

echo "✅ Done. docker pull $IMAGE:$TAG"