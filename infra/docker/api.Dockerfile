# DynamisData analytical API image.
#
# The image serves precomputed science from the PostgreSQL control/Gold schemas
# and bounded Parquet windows; it never downloads datasets or triggers processor
# runs. The code revision is injected so persisted provenance resolves exactly.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    DYNAMIS_ACCESS_LOG=1

RUN pip install --no-cache-dir "uv==0.12.4"

WORKDIR /app

# Dependency layer first: only the lockfile and project metadata invalidate it.
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY analytics ./analytics
COPY infra ./infra
COPY alembic.ini ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md LICENSE ./
RUN uv sync --locked --no-dev

# Non-root runtime.
RUN useradd --create-home --uid 10001 dynamis && chown -R dynamis:dynamis /app
USER dynamis

# Production/container processor provenance: the exact code revision is baked at
# image build time so persisted runs resolve to a real Git SHA.
ARG DYNAMIS_CODE_GIT_SHA=""
ENV DYNAMIS_CODE_GIT_SHA=${DYNAMIS_CODE_GIT_SHA}

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
CMD ["uv", "run", "--no-sync", "dynamis-serve", "--host", "0.0.0.0"]
