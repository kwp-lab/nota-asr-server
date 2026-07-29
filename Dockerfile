FROM python:3.12-slim

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
COPY pyproject.toml README.md LICENSE NOTICE /app/
COPY src /app/src

RUN python -m pip install --upgrade pip \
    && python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install .

EXPOSE 8010
CMD ["nota-asr-server"]

