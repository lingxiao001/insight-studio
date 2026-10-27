# Portable alternative; native Linux systemd deployment is also supported.
FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./
COPY deploy/wheels/ ./deploy/wheels/
RUN sha256sum -c deploy/wheels/SHA256SUMS && pip install --no-cache-dir --find-links deploy/wheels -r requirements.txt && useradd --uid 10001 --create-home insight
COPY backend/ ./
COPY LICENSE NOTICE LICENSING.md THIRD_PARTY_NOTICES.md ./
COPY --from=web /web/dist /app/static
RUN mkdir /data && chown insight:insight /data
USER insight
ENV DATA_DIR=/data STATIC_DIR=/app/static PYTHONUNBUFFERED=1
EXPOSE 8108
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8108/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8108", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
