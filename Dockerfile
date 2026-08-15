# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-alpine AS web

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build


# --- stage 2: bake the border index ----------------------------------------
# Countries do not move. The Natural Earth boundaries become a read-only
# SQLite R*Tree here, once, so nothing is parsed or held in memory at runtime.
FROM python:3.13-slim AS borders

WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/build_borders.py ./
RUN python build_borders.py /build/borders.db


# --- stage 3: runtime -------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SONDARO_STATIC_DIR=/app/static \
    SONDARO_BORDERS_DB=/app/api/borders.db

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi==0.115.6" \
        "uvicorn[standard]==0.34.0" \
        "httpx==0.28.1"

COPY api/ ./api/
COPY --from=borders /build/borders.db ./api/borders.db
COPY --from=web /web/dist ./static

# runs unprivileged; 7373 is container-internal so it can never clash
RUN useradd --system --uid 3002 --create-home sondaro \
    && mkdir -p /config \
    && chown -R sondaro:sondaro /config /app
USER sondaro

EXPOSE 7373

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7373/healthz').read()" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7373"]
