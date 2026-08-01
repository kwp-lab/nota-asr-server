# Development

## Setup

Use Python 3.10-3.12 and install the correct PyTorch/torchaudio build before the
project dependencies. The root README contains CPU commands.

## Tests

```bash
pytest
pytest --cov=nota_asr_server
```

Contract and API tests use fake backends and must not download models. Real
model smoke tests are operational checks and run separately.

For a Fun-ASR-Nano CPU smoke check, start a server configured with
`NOTA_PRELOAD_MODEL=fun-asr-nano`, submit an untracked sample with
`model=fun-asr-nano`, `response_format=verbose_json`, and `diarization=true`,
then verify non-empty text, timestamped segments, and speaker labels. Use a
controlled untracked two-speaker recording for meeting-wide validation. Never
commit the recording or transcript.

Copy `.env.example` to `.env` before starting the server. The local `.env` is
not committed because it may contain API keys; non-secret defaults remain in
the tracked example. Relative `NOTA_MODEL_DIR` paths are resolved from the
process working directory, which should be the repository root.
`NOTA_DATA_DIR` is resolved the same way and is ignored by Git.

## Change Checklist

- Preserve the compact OpenAI-compatible response.
- Run contract tests for both model-shaped fixtures.
- Update `docs/api-contract.md` for compatible clarifications.
- Create an ADR and increment `schema_version` for breaking changes.
- Never commit recordings, model weights, API keys, or `.env` files.
