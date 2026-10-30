# ---- build the dashboard ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git iptables && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY examples/ examples/
COPY --from=web /web/dist frontend/dist

# Two users. The server runs as root and is the only process holding the API keys. Repository code
# (setup and test commands) runs as the unprivileged `sandbox` user, which can't read root's environment.
RUN useradd --system --create-home --shell /usr/sbin/nologin sandbox \
 && mkdir -p /tmp/autofix-runs && chmod 755 /tmp/autofix-runs \
 && chmod -R go-w /app
# Visitor repos (public mode): "auto" enables them only after the server installs firewall rules that keep
# the sandbox user away from the cloud metadata service (169.254.169.254), private networks and localhost,
# and verifies them. Where the container can't change the firewall, they stay off. "0" forces demos only.
ENV PYTHONPATH=/app/backend AUTOFIX_WORK_DIR=/tmp/autofix-runs AUTOFIX_SANDBOX=user \
    AUTOFIX_ALLOW_USER_REPOS=auto PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn autofix.server:app --host 0.0.0.0 --port ${PORT}"]
