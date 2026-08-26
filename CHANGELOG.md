# Changelog

All notable changes to Nota ASR Server are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Generate the Linux Python SBOM in CI and Docker builds instead of committing
  a platform-specific root artifact that becomes stale after metadata-only lock
  changes; Windows Runtime and Manager SBOM generation remains unchanged.

## [0.4.0] - 2026-08-25

### Added

- Added versioned batch hotword requests with persisted idempotent snapshots,
  structured model capabilities, Paraformer decoder bias, and Fun-ASR-Nano
  prompt hotwords.

### Fixed

- Preferred installed managed model snapshots even under the `on_demand`
  policy, preventing FunASR from downloading redundant ModelScope cache copies
  and preserving offline startup after installation.
- Filtered request hotword values from third-party FunASR inference logs.

## [0.3.0] - 2026-08-22

### Fixed

- Shortened private Windows Runtime and release staging directory names so
  deeply nested Python wheel paths remain below legacy Windows path limits.
- Kept portable and installed Manager configuration ownership distinct: ZIP
  builds use their adjacent `config/server.toml`, while a future installer can
  mark its program directory so direct EXE and shortcut launches both use
  `%APPDATA%\NotaASR\server.toml`.
- Matched Nota Client tray behavior in the Manager: a single left click restores
  and focuses the window, while only right click opens the context menu; the
  global-status indicator is now geometrically centered instead of font-based.
- Separated the Manager header's Server lifecycle state from temporary action
  feedback, which now appears left-aligned and vertically centered in a
  dedicated edge-to-edge global status bar with only a top divider at the
  bottom.
- Preserved TOML-relative model and data roots when the Manager saves portable
  Runtime settings, while retaining absolute paths for external directories.
- Opened the exact normalized `<data_root>/logs` directory from the Manager
  instead of silently falling back to the Windows Documents folder when an
  unresolved relative path or shell-launch failure was encountered.
- Loaded a Windows system CJK font as an egui fallback so the native Manager
  renders its Simplified Chinese interface instead of square placeholder
  glyphs without bundling an additional font in the Runtime.
- Removed the unused Common Controls v6 tray-menu feature that made the
  Windows Manager import `TaskDialogIndirect` without an embedded activation
  manifest and fail before startup on Windows.

### Added

- Added a bounded real-time Server log viewer to the Windows Manager with
  incremental file following, text filtering, automatic scrolling, health-probe
  suppression, log-directory access, and a display-only clear action.
- Added a versioned TOML configuration contract, structured configuration,
  model-lifecycle and diagnostic CLI commands, and an explicit model catalog
  with resumable staging and snapshot verification.
- Added a movable Windows 11 x64 CPU one-folder builder using self-contained
  CPython 3.12.12 and locked PyTorch/torchaudio 2.11.0 CPU dependencies.
- Added the native Rust Nota ASR Manager with tray lifecycle, Job Object child
  cleanup, model download progress, diagnosis, safe configuration writes,
  external-server detection, and verified model-directory migration.
- Added a clean-worktree, owner-local portable ZIP release pipeline with Manager
  code signing, SHA-256 manifests, and distinct Windows Python and Rust
  compliance inventories. An installed edition is deferred and is not part of
  the current repository release path.

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

- Allowed owner-built public portable ZIP releases to be explicitly unsigned
  with `-UnsignedRelease`, while publishing a SHA-256 checksum and manifest that
  disclose the signature policy and documenting Windows publisher warnings.
- Redesigned the native Manager as a dark two-column control room with models
  beside the primary live-log workspace, removed the duplicated Server summary,
  moved collapsed-on-start settings below the model list, and surfaced the
  configured/running preload model as a model-item badge. Its window,
  notification-area, and embedded executable icon use the same handwritten M
  artwork.
- Reduced the default Windows one-folder size by disabling eager whole-runtime
  bytecode compilation and pruning native-extension headers and `.lib` build
  inputs after installation, while retaining post-prune import checks.
- Separated the default transcription model from the startup preload model and
  passed the CLI-resolved `Settings` instance directly into FastAPI.
- Updated Paraformer to the complete SeACo model identifier and pinned the
  stable VAD, punctuation, CAM++ and Paraformer revisions in the shared catalog.
- Windows Runtime defaults now bind loopback and require explicit model
  installation, while existing `.env`, Docker, systemd, and on-demand source
  deployments retain their behavior.

- Added an always-reported pull-request gate that runs only the server or
  compliance checks affected by changed paths, allowing `main` protection
  without running application checks for documentation-only changes.
- Added path-scoped pull-request and `main` CI for fake-backend tests and
  dependency compliance, with superseded runs cancelled to conserve hosted
  runner time.
- Defined the Linux CPU deployment as the Server license-inventory baseline
  and prevented virtual-environment Python symlinks from leaking CI runner
  packages into generated compliance artifacts.
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

[Unreleased]: https://github.com/kwp-lab/nota-asr-server/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/kwp-lab/nota-asr-server/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kwp-lab/nota-asr-server/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kwp-lab/nota-asr-server/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kwp-lab/nota-asr-server/releases/tag/v0.1.0
