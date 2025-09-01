# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install only what's needed for wheel resolution (no compilers typically needed due to manylinux wheels)
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# Final runtime image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m -u 10001 appuser

WORKDIR /app

# Copy wheels and install offline for reproducibility
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

# Copy application source
COPY main.py .

# Ensure correct ownership
RUN chown -R appuser:appuser /app
USER appuser

# Default entrypoint
ENTRYPOINT ["python", "-u", "main.py"]
