# MeshCtx Enterprise — 多 Agent 集群镜像
FROM python:3.12-slim

LABEL org.opencontainers.image.title="meshctx-enterprise"
LABEL org.opencontainers.image.description="17-Brain Multi-Agent Enterprise Platform"
LABEL org.opencontainers.image.version="0.1.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 企业模块
COPY a2a_protocol.py .
COPY agent_registry.py .
COPY agent_roles.yaml .
COPY human_in_loop.py .

# Agent 启动入口
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV MESHCTX_REDIS_TLS=false

EXPOSE 8080 9090

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
