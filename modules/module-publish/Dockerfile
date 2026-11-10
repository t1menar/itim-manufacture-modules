ARG PYTHON_IMAGE=python:3.12-slim

# Build from repository root: docker build -f modules/module-publish/Dockerfile .
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /src
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY packages/mf-storage /src/packages/mf-storage
COPY modules/module-publish/pyproject.toml modules/module-publish/README.md /src/modules/module-publish/
COPY modules/module-publish/src /src/modules/module-publish/src
COPY modules/module-publish/schemas /src/modules/module-publish/schemas
COPY modules/module-publish/migrations /src/modules/module-publish/migrations
COPY modules/module-publish/alembic.ini /src/modules/module-publish/alembic.ini
WORKDIR /src/modules/module-publish
RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev --no-editable; \
    else uv lock && uv sync --no-dev --no-editable; fi

FROM ${PYTHON_IMAGE}
# sftp copies the video to the public video host (upload mode url)
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin publish
COPY --from=build /src/modules/module-publish/.venv /app/.venv
COPY --from=build /src/modules/module-publish/schemas /app/.venv/lib/python3.12/schemas
COPY --from=build /src/modules/module-publish/migrations /app/.venv/lib/python3.12/migrations
COPY --from=build /src/modules/module-publish/alembic.ini /app/.venv/lib/python3.12/alembic.ini
COPY --from=build /src/modules/module-publish/src /app/src
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
# uv console_scripts keep the build-path shebang; rewrite for the runtime venv.
RUN sed -i '1s|^#!.*|#!/app/.venv/bin/python|' /app/.venv/bin/publish \
 && find /app/.venv/bin -type f -executable -exec sed -i '1s|^#!/src/.*/.venv/bin/python|#!/app/.venv/bin/python|' {} +
USER 10002
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:' + os.environ['PUBLISH_LISTEN_ADDR'].rsplit(':', 1)[1] + '/health', timeout=2)"]
ENTRYPOINT ["publish"]
CMD ["serve"]
