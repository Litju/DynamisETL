# Dagster orchestration image (RES-96 foundation only).
#
# Profile-gated in docker-compose.yml: the RES-96 acceptance gates do not require
# this image to build, and no RES-97+ provider adapter is installed here.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN pip install --no-cache-dir "uv==0.12.4"

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
COPY sources ./sources
COPY infra ./infra
COPY alembic.ini ./

RUN uv sync --locked --no-dev

EXPOSE 3000

CMD ["uv", "run", "dagster", "dev", "-f", "src/dynamis/orchestration/definitions.py", "-h", "0.0.0.0", "-p", "3000"]
