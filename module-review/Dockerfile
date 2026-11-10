ARG PYTHON_IMAGE=python:3.12-slim

# Build from repository root: docker build -f module-review/Dockerfile .
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /src
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY packages/mf-storage /src/packages/mf-storage
COPY module-review/pyproject.toml module-review/README.md /src/module-review/
COPY module-review/src /src/module-review/src
COPY module-review/schemas /src/module-review/schemas
COPY module-review/migrations /src/module-review/migrations
COPY module-review/alembic.ini /src/module-review/alembic.ini
WORKDIR /src/module-review
RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev --no-editable; \
    else uv lock && uv sync --no-dev --no-editable; fi

FROM ${PYTHON_IMAGE}
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin review
COPY --from=build /src/module-review/.venv /app/.venv
COPY --from=build /src/module-review/schemas /app/.venv/lib/python3.12/schemas
COPY --from=build /src/module-review/migrations /app/.venv/lib/python3.12/migrations
COPY --from=build /src/module-review/alembic.ini /app/.venv/lib/python3.12/alembic.ini
COPY --from=build /src/module-review/src /app/src
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
# uv console_scripts keep the build-path shebang; rewrite for the runtime venv.
RUN sed -i '1s|^#!.*|#!/app/.venv/bin/python|' /app/.venv/bin/review \
 && find /app/.venv/bin -type f -executable -exec sed -i '1s|^#!/src/.*/.venv/bin/python|#!/app/.venv/bin/python|' {} +
USER 10002
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:' + os.environ['REVIEW_LISTEN_ADDR'].rsplit(':', 1)[1] + '/health', timeout=2)"]
ENTRYPOINT ["review"]
CMD ["serve"]
