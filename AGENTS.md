# Agent Guide

This repository is the server-side ASR component for the Nota Windows meeting
recorder. Read `docs/README.md` before changing code.

Non-negotiable constraints:

- Keep `/v1/audio/transcriptions` compatible with OpenAI multipart clients.
- Treat the `verbose_json` response in `docs/api-contract.md` as a versioned API contract.
- Never expose raw FunASR model output directly to clients.
- Preserve model independence: SenseVoice and Paraformer must pass through adapters.
- Speaker ids are meeting-local anonymous labels, not identities.
- The batch upload API is not a realtime streaming API.
- Add or update contract tests when changing schemas or normalization behavior.
- Update the relevant document and ADR when changing an architectural decision.

