# ---- build the dashboard ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY examples/ examples/
COPY --from=web /web/dist frontend/dist
RUN useradd -m autofix && chown -R autofix /app
USER autofix
ENV PYTHONPATH=/app/backend AUTOFIX_WORK_DIR=/tmp/autofix-runs PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn autofix.server:app --host 0.0.0.0 --port ${PORT}"]
