# ── Stage 1: builder ────────────────────────────────────────────────────────
# Install dependencies in an isolated layer so the final image only copies
# the compiled packages, not pip caches or build tools.
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps needed for some packages (psycopg2, bcrypt, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user for least-privilege execution
RUN addgroup --system bookbrief && adduser --system --ingroup bookbrief bookbrief

# Runtime system deps (libpq for asyncpg/psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY backend/ ./

# Ensure non-root user owns the app directory
RUN chown -R bookbrief:bookbrief /app

USER bookbrief

# Expose default port (overridden by $PORT on Render)
EXPOSE 8000

# Default: run migrations then start server.
# In Render this is overridden by the startCommand in render.yaml.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --loop uvloop --http httptools --proxy-headers"]
