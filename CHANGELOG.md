# Changelog

All notable changes to Nota ASR Server are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added a bilingual contribution guide covering API compatibility, synthetic
  test data, model-independent boundaries, and pull-request checks.
- Added generated production dependency notices, a CycloneDX SBOM, model
  license guidance, and a CI license-policy gate.

- Added authenticated, stateless CAM++ speaker-embedding extraction for
  bounded 16 kHz mono PCM16 WAV samples, including capability discovery,
  stable model fingerprints, strict validation, and request-scoped cleanup.
- Added bounded two-stage CAM++ candidate and window analysis that returns
  clean original-range offsets for reusable voiceprint enrollment while still
  providing a preview-only result for manual naming when audio quality does
  not meet biometric storage gates.
- Added lazy-loaded `fun-asr-nano` API support using the official
  `FunAudioLLM/Fun-ASR-Nano-2512` PyTorch checkpoint, FSMN-VAD, CAM++, native
  punctuation, ITN, timestamps, and meeting-wide speaker reconciliation.
- Added model-specific language prompt mapping for Chinese, English, Japanese,
  and Cantonese while reporting `und` for Nano automatic-language requests.

### Changed

- Added path-scoped pull-request and `main` CI for fake-backend tests and
  dependency compliance, with superseded runs cancelled to conserve hosted
  runner time.
- Docker CPU deployments now install the exact `uv.lock` `cpu` extra instead
  of resolving PyTorch and application dependencies during every build, and
  carry the project and third-party legal files in the image.

- Unified the MIT license copyright holder and project metadata under `kwp-lab`.
- Separated dense window-level CAM++ clustering from sparse whole-meeting
  centroid clustering. Meeting finalization now uses deterministic cosine
  agglomerative clustering for every centroid count, with conservative
  complete linkage in automatic mode instead of switching to FunASR spectral
  clustering at 20 centers.
- Refined SenseVoice and Fun-ASR-Nano whole-meeting diarization by preserving
  CAM++ chunk traces and ASR token timestamps, reconciling them against global
  speaker clusters, and safely splitting a VAD segment only when text alignment
  is exact; the public response schema remains unchanged.
- Advertised Fun-ASR-Nano in the default enabled model list while retaining
  SenseVoice as the startup preload and default transcription model.
- Changed Paraformer diarization output from one speaker per VAD region to one
  speaker per CT-Punc sentence, while retaining meeting-wide CAM++ clustering.
- Bounded a requested speaker count by the available meeting centroids so
  sparse valid voice data can return fewer speakers instead of failing final
  clustering.
- Treated a requested speaker count as a safety target, allowing additional
  anonymous speakers instead of forcing weakly similar participants into one
  label, and applied the same 0.78 similarity safety line in automatic and
  specified-count modes.

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
