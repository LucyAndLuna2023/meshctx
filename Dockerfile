# meshctx Dockerfile
# 2026-08-25 004meshctx 审计修复: 端口 3000→3001 (产品统一端口), version label 同步, healthcheck 路径修正
FROM python:3.11-slim

LABEL org.opencontainers.image.title="meshctx"
LABEL org.opencontainers.image.description="World's First Self-Evolving Agent System"
LABEL org.opencontainers.image.version="3.120.6"

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles

COPY . .

# 数据目录: 与 install.sh/cli.py 一致 (HOME 下 ~/.meshctx)
RUN mkdir -p /root/.meshctx/logs

EXPOSE 3001

ENV MESHCTX_PORT=3001
ENV MESHCTX_HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3001/health || exit 1

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "3001"]
