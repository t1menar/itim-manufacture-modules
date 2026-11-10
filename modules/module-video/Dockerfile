# Module image (03 section 11). Build from module-video/:  docker build -t module-video:dev .
# The package is installed editable from /app/src so that prompts/, reference/ and agent/prices.json
# next to it are found at run time (mvideo resolves them relative to the source tree).
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM ${PYTHON_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mvideo
WORKDIR /app
COPY --from=build /app /app
COPY prompts ./prompts
COPY reference ./reference
COPY agent/prices.json ./agent/prices.json
COPY fonts/ /usr/share/fonts/manufacture/
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 FFMPEG=/usr/bin/ffmpeg
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:' + os.environ['VIDEO_LISTEN_ADDR'].rsplit(':', 1)[1] + '/health', timeout=2)"]
ENTRYPOINT ["mvideo"]
