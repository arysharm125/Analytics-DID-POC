# syntax=docker/dockerfile:1

# This is the Dockerfile that builds a production DIDSvc backend API image. It
# uses a python image to build requirements from source, then it copies all
# artefacts to a production image.

# =========================
# Build stage
# =========================
FROM python:3.12-slim AS build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    gcc \
    libffi-dev \
    libssl-dev \
    cargo \
    git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create virtual environment
RUN python -m venv /opt/did-venv
ENV PATH="/opt/did-venv/bin:$PATH"

# Upgrade tooling
RUN pip install --upgrade setuptools wheel

# Copy requirements
COPY requirements.txt .
# Build wheels
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels \
 && rm -f /wheels/ecdsa-*.whl || true

# Generate version_metadata.py using bind-mounted .git directory
# This temporarily mounts the host's .git directory without copying it into the image
RUN --mount=type=bind,source=.git,target=/tmp/.git \
    GIT_SHA=$(git --git-dir=/tmp/.git rev-parse --short=6 HEAD 2>/dev/null || echo "unknown") && \
    mkdir -p /app/app && \
    echo "# Auto-generated during Docker build" > /app/app/version_metadata.py && \
    echo "VERSION_TAG = \"docker\"" >> /app/app/version_metadata.py && \
    echo "GIT_SHA = \"${GIT_SHA}\"" >> /app/app/version_metadata.py

# =========================
# Runtime stage
# =========================
FROM python:3.12-slim

# Install runtime libs AND necessary binary deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    libffi8 \
 && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN addgroup --system appgroup \
 && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy virtual environment
COPY --from=build /opt/did-venv /opt/did-venv
ENV PATH="/opt/did-venv/bin:$PATH"

# Install dependencies from wheels ONLY
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
 && pip uninstall -y ecdsa || true \
 && rm -rf /wheels

# Copy application code (allowlist approach)
COPY app/ /app/app/
COPY requirements.txt /app/
COPY contexts/ /app/contexts/
COPY deployment/logging.ini /app/deployment/

# Copy generated version_metadata.py from build stage
COPY --from=build /app/app/version_metadata.py /app/app/version_metadata.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=45603

USER appuser

EXPOSE 45603

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "45603", "--log-level", "info", "--no-access-log"]
