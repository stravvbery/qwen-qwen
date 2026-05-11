# syntax=docker/dockerfile:1.7
# Multi-stage build: compile the React frontend, then install the Python
# backend and copy the built static assets into it.

# --- frontend build ----------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- backend runtime ---------------------------------------------------------
FROM python:3.12-slim AS backend
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl tini \
  && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
RUN pip install --upgrade pip && pip install /app/backend

COPY --from=frontend /app/frontend/dist /app/backend/static

WORKDIR /app/backend
ENV STATIC_DIR=/app/backend/static \
    DATA_DIR=/data

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
