# TRAFFICINTEL AI - Backend API
#
# Two stages so the build toolchain needed to compile wheels never ships in the
# runtime image, and the runtime runs as a non-root user: a traffic control
# system should not hand a container escape a root shell.

# ---------------------------------------------------------------------------
# Stage 1: build wheels
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# libpq5 only: the client library, not the build headers.
# curl is the container healthcheck's only dependency.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 trafficintel

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=trafficintel:trafficintel . .

USER trafficintel

EXPOSE 8000

# Readiness, not liveness: the orchestrator should treat an instance whose
# schema has drifted as unfit to serve, not merely as a running process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ready || exit 1

# Alembic is NOT run here. The schema is migrated deliberately by an operator
# or a release job, never as a side effect of a container starting: two
# replicas booting at once would otherwise race each other through the same
# migration.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
