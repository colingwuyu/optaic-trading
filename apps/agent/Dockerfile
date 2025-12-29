FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
COPY apps/agent apps/agent
COPY libs libs

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "python", "-m", "apps.agent.main"]
