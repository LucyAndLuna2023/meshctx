# meshctx Dockerfile
FROM python:3.11-slim

LABEL org.opencontainers.image.title="meshctx"
LABEL org.opencontainers.image.description="World's First Self-Evolving Agent System"
LABEL org.opencontainers.image.version="2.28.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles

COPY . .

RUN mkdir -p /root/.meshctx/logs

EXPOSE 3000

ENV MESHCTX_PORT=3000
ENV MESHCTX_HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3000/health || exit 1

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "3000"]
