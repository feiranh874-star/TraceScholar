FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    ENABLE_API_DOCS=false \
    STORAGE_DIR=/app/data \
    PORT=8000

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements-production.txt /app/backend/requirements-production.txt
RUN pip install --no-cache-dir -r /app/backend/requirements-production.txt

RUN groupadd --gid 10001 tracescholar \
    && useradd --uid 10001 --gid 10001 --no-create-home tracescholar \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data

COPY --chown=10001:10001 backend/app /app/backend/app
COPY --chown=10001:10001 frontend /app/frontend
USER 10001:10001
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c 'import os,urllib.request; urllib.request.urlopen("http://127.0.0.1:" + os.getenv("PORT", "8000") + "/health", timeout=3)'

# One process is required for the local store lock and in-memory limits.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --no-proxy-headers"]
