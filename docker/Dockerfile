# funscript-gen image: the CLI and the web UI. Built from the repository root (see docker/README.md):
#   docker build -f docker/Dockerfile -t funscript-gen .
#   docker build -f docker/Dockerfile --build-arg WITH_POSE=1 -t funscript-gen:pose .   # + skeleton mode (CPU torch)
FROM python:3.15-slim-bookworm

# OpenCV (opencv-python) needs libGL and GLib at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv

ARG WITH_POSE=0
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
# Dependencies first (cached while only the source changes), versions from uv.lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project $([ "$WITH_POSE" = 1 ] && echo --extra pose)
COPY README.md LICENSE THIRD_PARTY_NOTICES.md .env.example ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev $([ "$WITH_POSE" = 1 ] && echo --extra pose)

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

# Everything the program writes is relative to the working directory or under $HOME: .env, the web UI's remembered
# settings, out/, and the AI / part-box / model caches (~/.cache). Both point at /data, the one volume to keep.
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/data \
    GRADIO_TEMP_DIR=/data/tmp
WORKDIR /data
VOLUME /data
EXPOSE 7860

ENTRYPOINT ["entrypoint.sh"]
CMD ["webui"]
