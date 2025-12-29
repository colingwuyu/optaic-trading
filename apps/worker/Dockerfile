FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the root to get workspaces
COPY pyproject.toml uv.lock ./
COPY apps/worker apps/worker
COPY libs libs

# Install dependencies
RUN uv sync --frozen --no-dev

# Run the application
CMD ["uv", "run", "python", "-m", "apps.worker.main"]
