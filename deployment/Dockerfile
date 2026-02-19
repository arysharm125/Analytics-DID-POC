# deployment/Dockerfile

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
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create virtual environment
RUN python -m venv /opt/did-venv
ENV PATH="/opt/did-venv/bin:$PATH"

# Upgrade tooling
RUN pip install --upgrade pip==25.3 setuptools wheel

# Copy requirements
COPY requirements.txt .
# Build wheels
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels \
 && rm -f /wheels/ecdsa-*.whl || true

# =========================
# Runtime stage
# =========================
FROM python:3.12-slim

# Install runtime libs AND Audit Tool Dependencies (sshpass, ssh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
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
COPY deployment/logging.ini /app/deployment/

# Fix ownership
RUN chown -R appuser:appgroup /app /opt/did-venv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=45603

USER appuser

EXPOSE 45603

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "45603", "--log-level", "info", "--access-log"]
