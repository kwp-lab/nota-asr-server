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

## Change Checklist

- Preserve the compact OpenAI-compatible response.
- Run contract tests for both model-shaped fixtures.
- Update `docs/api-contract.md` for compatible clarifications.
- Create an ADR and increment `schema_version` for breaking changes.
- Never commit recordings, model weights, API keys, or `.env` files.

