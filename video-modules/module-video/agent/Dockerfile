# Agent image `video-agent` (03 section 5.1). Build from module-video/:
#   docker build -f agent/Dockerfile -t video-agent:dev .
# Pin the result by digest in settings agent.image. The Claude Code CLI is bundled in the
# claude-agent-sdk wheel (verified for 0.2.179: CLI 2.1.319), so no Node.js is needed.
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --extra agent

FROM ${PYTHON_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --create-home --home-dir /work --shell /usr/sbin/nologin agent \
 && mkdir -p /opt/agent /job /in /ref /src /out /work && chown agent /work /out
COPY --from=build /app/.venv /app/.venv
COPY agent/runner.py agent/prices.json /opt/agent/
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HOME=/work
USER 10001
WORKDIR /work
ENTRYPOINT []
CMD ["python", "/opt/agent/runner.py", "/job/run.json"]
