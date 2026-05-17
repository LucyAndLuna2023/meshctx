# MeshCtx Docker — 一键部署
# docker build -t meshctx . && docker run -d -p 3000:3000 meshctx
FROM python:3.12-slim

LABEL org.opencontainers.image.title="MeshCtx"
LABEL org.opencontainers.image.description="World's first self-evolving AI agent — 13 brain regions, 100+ models, 28 providers"
LABEL org.opencontainers.image.url="https://meshctx.com"
LABEL org.opencontainers.image.version="2.17.0"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash meshctx && \
    mkdir -p /app /home/meshctx/.meshctx && \
    chown -R meshctx:meshctx /app /home/meshctx/.meshctx

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (includes brain modules for Docker build)
COPY src/ ./src/
COPY plugins/ ./plugins/
COPY docs/ ./docs/
COPY meshctx.yaml ./meshctx.yaml
COPY meshctx_desktop.py ./meshctx_desktop.py 2>/dev/null || true
COPY logo.png logo.ico logo.icns ./ 2>/dev/null || true
COPY README.md LICENSE LEGAL.md ./ 2>/dev/null || true

# Fix permissions
RUN chown -R meshctx:meshctx /app

# Switch to non-root
USER meshctx

# Expose web UI port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:3000/api/version || exit 1

# Start
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "3000"]
