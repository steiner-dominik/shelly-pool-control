# ---- frontend build (runs on the build platform, output is arch-neutral) ----
FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VERSION=dev
ENV POOL_VERSION=$VERSION
# vite outDir is ../server/app/static (relative to /frontend)
RUN mkdir -p /server/app/static && npm run build

# ---- runtime ----------------------------------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POOL_DATA_DIR=/data \
    POOL_PORT=8080

WORKDIR /app
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
COPY --from=frontend /server/app/static ./app/static
COPY shared/logic-spec.md ./shared/logic-spec.md

ARG VERSION=dev
ENV POOL_VERSION=$VERSION

# /data holds the SQLite DB and backups. The image defaults to root so the
# Home Assistant Supervisor data mount works out of the box; for standalone
# deployments you can drop privileges with `user:` in docker-compose (see
# deploy/docker-compose.example.yml).
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"POOL_PORT\",\"8080\")}/healthz')" || exit 1

CMD ["python", "-c", "import os, uvicorn; uvicorn.run('app.main:app', host=os.environ.get('POOL_BIND','0.0.0.0'), port=int(os.environ.get('POOL_PORT','8080')), log_level='info')"]
