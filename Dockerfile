# ── Stage 1: builder ────────────────────────────────────────────────────────
# Build context = repo root (Render default)
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY bookbrief-ai/backend/requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN addgroup --system bookbrief && adduser --system --ingroup bookbrief bookbrief

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

# Copy backend source into /app/
# After this: /app/app/main.py, /app/alembic/, /app/alembic.ini, etc.
COPY bookbrief-ai/backend/ ./

# main.py computes ROOT_DIR = Path(__file__).parent.parent.parent = /
# so it serves frontend from /frontend and static from /static
COPY bookbrief-ai/frontend/ /frontend/

RUN chown -R bookbrief:bookbrief /app && chown -R bookbrief:bookbrief /frontend

USER bookbrief

EXPOSE 8000

# Render injects $PORT; fall back to 8000 for local docker run
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --loop uvloop --http httptools --proxy-headers --forwarded-allow-ips='*'"]
