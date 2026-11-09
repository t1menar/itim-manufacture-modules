ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml README.md ./
COPY src ./src
COPY schemas ./schemas
COPY migrations ./migrations
COPY alembic.ini ./
# Lockfile may be generated during image build when absent in the build context.
RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev --no-editable; \
    else uv lock && uv sync --no-dev --no-editable; fi

FROM ${PYTHON_IMAGE}
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin publish
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/schemas /app/schemas
COPY --from=build /app/migrations /app/migrations
COPY --from=build /app/alembic.ini /app/alembic.ini
COPY --from=build /app/src /app/src
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10002
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:' + os.environ['PUBLISH_LISTEN_ADDR'].rsplit(':', 1)[1] + '/health', timeout=2)"]
ENTRYPOINT ["publish"]
CMD ["serve"]
