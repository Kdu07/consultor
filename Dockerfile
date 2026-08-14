# --- estágio 1: build do frontend ---
# Nada de COPY static/ aqui: vite.config.ts tem emptyOutDir: true e apagaria a pasta.
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package*.json frontend/
RUN npm ci --prefix frontend
COPY frontend/ frontend/
RUN npm run build --prefix frontend

# --- estágio 2: runtime ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ app/
# docs/ é lido em runtime: app/seeds.py (perfil de risco) e app/agent/system_prompt.py.
COPY docs/ docs/
COPY --from=frontend /build/static/ static/
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
