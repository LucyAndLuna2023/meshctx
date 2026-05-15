# MeshCtx Docker Deployment
# v2.11 — 100模型·28供应商·全脑仿真Agent
FROM python:3.12-slim

LABEL org.opencontainers.image.title="MeshCtx"
LABEL org.opencontainers.image.description="World's first self-evolving AI agent platform — 13 brain regions, 100 models, code sandbox"
LABEL org.opencontainers.image.url="https://meshctx.com"
LABEL org.opencontainers.image.version="2.11.0"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && \
    rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash meshctx && \
    mkdir -p /app /home/meshctx/.meshctx && \
    chown -R meshctx:meshctx /app /home/meshctx/.meshctx

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Install MeshCtx
RUN pip install --no-cache-dir -e .

# Switch to non-root
USER meshctx

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start
CMD ["python", "-m", "src.cli", "start", "--host", "0.0.0.0", "--port", "8000"]
