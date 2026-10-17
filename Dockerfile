# Seekho Saathi: one image = built web app + API (see docs/DEPLOY.md). Data lives in a bucket and is restored at start (DATA_BUCKET).
FROM node:22-bookworm-slim AS web
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
COPY packages /app/packages
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
COPY services/api/pyproject.toml services/api/uv.lock services/api/README.md ./services/api/
RUN cd services/api && uv sync --frozen --no-dev --no-install-project
COPY services/api ./services/api
RUN cd services/api && uv sync --frozen --no-dev
COPY --from=web /app/apps/web/dist ./apps/web/dist
COPY apps/web/public/favicon.svg apps/web/public/icons.svg ./apps/web/public/
RUN mkdir -p data apps/web/public/lessons apps/web/public/audio apps/web/public/img apps/web/public/chat logs
ENV PORT=8080 AUTH_MODE=on STORE=firestore
EXPOSE 8080
# no --workers: room state and jobs are in memory, so ONE process serves everything (max-instances=1 on Cloud Run)
CMD ["sh", "-c", "exec /app/services/api/.venv/bin/uvicorn ai_teacher_api.server:root --host 0.0.0.0 --port ${PORT} --ws-ping-interval 20 --ws-ping-timeout 30 --timeout-keep-alive 75"]
