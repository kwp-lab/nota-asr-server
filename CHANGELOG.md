# Changelog

All notable changes to Nota ASR Server are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added lazy-loaded `fun-asr-nano` API support using the official
  `FunAudioLLM/Fun-ASR-Nano-2512` PyTorch checkpoint, FSMN-VAD, CAM++, native
  punctuation, ITN, timestamps, and meeting-wide speaker reconciliation.
- Added model-specific language prompt mapping for Chinese, English, Japanese,
  and Cantonese while reporting `und` for Nano automatic-language requests.

### Changed

- Advertised Fun-ASR-Nano in the default enabled model list while retaining
  SenseVoice as the startup preload and default transcription model.

## [0.2.0] - 2026-07-31

### Added

- Added Nota batch protocol v1 with idempotent job creation, resumable Ogg
  uploads, durable status, cancellation, resume, result retrieval, and
  client-confirmed deletion.
- Added bounded five-minute inference windows with persistent checkpoints,
  overlap-aware merging, and meeting-wide CAM++ speaker reconciliation.
- Added recovery of uploads and completed inference windows across service
  restarts, plus automatic cleanup of abandoned jobs.
- Added a PyTorch benchmark for comparing CPU and Intel XPU execution without
  writing transcript content to reports.
- Added complete English and Simplified Chinese setup, deployment, API,
  security, operations, CPU, and Intel XPU documentation.

### Changed

- Reduced the default maximum meeting duration from six hours to four hours.
- Added a persistent `NOTA_DATA_DIR` for SQLite job state, uploaded recordings,
  window results, and final responses.
- Updated Docker Compose to persist both model weights and batch-job data.
- Kept the existing OpenAI-compatible transcription endpoint and verbose JSON
  1.0 response contract unchanged.

### Security

- Bound durable jobs to API-key fingerprints without storing the original key.
- Kept audio, transcript text, authorization data, and raw model output out of
  technical logs.

## [0.1.0] - 2026-07-31

### Added

- Added the initial OpenAI-compatible SenseVoice and Paraformer transcription
  service with CAM++ speaker diarization.
- Added health, readiness, model discovery, optional Bearer authentication,
  Docker, and systemd deployment support.

[Unreleased]: https://github.com/kwp-lab/nota-asr-server/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kwp-lab/nota-asr-server/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kwp-lab/nota-asr-server/releases/tag/v0.1.0
