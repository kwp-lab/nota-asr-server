FROM python:3.12-slim

ARG UV_VERSION=0.9.2

LABEL org.opencontainers.image.title="Nota ASR Server" \
      org.opencontainers.image.description="Local ASR service for Nota" \
      org.opencontainers.image.source="https://github.com/kwp-lab/nota-asr-server" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NOTA_HOST=0.0.0.0 \
    NOTA_PORT=8010 \
    NOTA_DEVICE=cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m pip install --no-cache-dir "uv==$UV_VERSION"

COPY pyproject.toml uv.lock README.md LICENSE NOTICE THIRD_PARTY_LICENSES.md THIRD_PARTY_NOTICES.txt MODEL_LICENSES.md /app/
RUN uv sync --frozen --no-dev --extra cpu --no-install-project

COPY src /app/src
COPY scripts/generate_license_artifacts.py scripts/license-policy.json /app/scripts/
RUN uv sync --frozen --no-dev --extra cpu \
    && uv run --no-sync python scripts/generate_license_artifacts.py \
       --python /app/.venv/bin/python \
       --check \
       --sbom-output /app/bom.cyclonedx.json

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8010
CMD ["nota-asr-server"]
