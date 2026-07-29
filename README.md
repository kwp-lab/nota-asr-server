# Nota ASR Server

Nota ASR Server provides a stable OpenAI-compatible transcription endpoint for
the Nota Windows meeting recorder. It normalizes SenseVoice and Paraformer
outputs into one versioned response contract and adds speaker diarization with
CAM++.

## Current Scope

- Batch upload of a completed meeting recording.
- `POST /v1/audio/transcriptions` with `json` and `verbose_json` responses.
- SenseVoice as the default model; Paraformer is available as a lazy-loaded alias.
- VAD-based segments and meeting-local speaker labels.
- Optional Bearer API key authentication.
- CPU-first deployment with a single inference slot by default.

Realtime transcription is intentionally outside the v0.1 scope. See
[`docs/business-context.md`](docs/business-context.md).

## Local Development

Install a device-appropriate PyTorch build first. CPU example:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e '.[dev]'
```

Run tests without loading real models:

```bash
pytest
```

Start the service:

```bash
NOTA_PORT=8010 nota-asr-server
```

The first start downloads SenseVoice, FSMN-VAD, and CAM++. Check readiness at
`http://localhost:8010/ready`.

The default listener is `0.0.0.0:8010`; another LAN computer can replace
`localhost` with the server's LAN address. See `docs/security.md` before making
the endpoint reachable outside an isolated development network.

## Request

```bash
curl http://localhost:8010/v1/audio/transcriptions \
  -F file=@meeting.wav \
  -F model=sensevoice \
  -F response_format=verbose_json \
  -F diarization=true
```

When `NOTA_API_KEYS` is configured, add `Authorization: Bearer <key>`.

## Documentation

Start with [`docs/README.md`](docs/README.md). The API contract, model choices,
operations, security boundary, and architectural decisions are documented there.
