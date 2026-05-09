# ============================================================
# meshctx Dockerfile
# 多阶段构建，轻量高效
# ============================================================

# ── 构建阶段 ─────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.txt .

# 安装 Python 依赖到临时目录
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── 运行阶段 ─────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 安装运行时必要的系统库（chromadb/sentence-transformers 可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 复制项目源码
COPY src/ ./src/
COPY requirements.txt .

# 创建数据目录（ChromaDB 持久化存储）
RUN mkdir -p /app/data/chroma

# 暴露端口
EXPOSE 8000

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CHROMA_PERSIST_DIR=/app/data/chroma

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 运行应用
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
