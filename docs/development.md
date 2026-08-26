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

Hotword changes require capability-schema, normalization, idempotency,
restart persistence, per-window mapping, unsupported-model, and privacy tests.
Automated tests must not call DashScope or include real meeting terminology.

Actual model influence is checked separately with the opt-in
`examples/verify_hotword_effect.py` A/B probe. It submits the same Ogg audio
without and with hotwords and is deliberately outside `tests/`, so normal
`pytest` and CI runs never execute it. See `examples/README.md` for usage and
exit-code semantics.

Windows product changes also require the pinned Rust toolchain checks:

```powershell
cargo fmt --all -- --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
```

The Manager executable is not a standalone artifact: it resolves
`runtime/python/python.exe` relative to its own directory. To exercise a local
release build, copy it into an already built one-folder before launching it:

```powershell
cargo build --release --locked
Copy-Item .\target\release\NotaASRManager.exe `
  .\dist\nota-asr-runtime\NotaASRManager.exe
.\dist\nota-asr-runtime\NotaASRManager.exe `
  --config .\dist\nota-asr-runtime\config\server.toml
```

Running `target/release/NotaASRManager.exe` directly is unsupported because
that directory does not contain the Server Runtime. The release script performs
this assembly automatically before creating the portable ZIP.

The workspace is fixed to Rust 1.96.0 and commits `Cargo.lock`. A Runtime build
requires Windows 11 x64, uv 0.9.2, and the frozen `uv.lock`; it installs
CPython 3.12.12 from uv's `python-build-standalone` distribution and copies
locked PyTorch/torchaudio 2.11.0 CPU files into an isolated tree. It must not
link to the build machine's uv cache, source checkout, or Python installation.

The Manager build uses the Windows SDK resource compiler discovered by
`winresource` to embed its multi-size executable icon. Public portable ZIP
releases may be built unsigned by explicitly passing `-UnsignedRelease`; this
keeps the absence of an Authenticode publisher identity visible in the release
manifest. A certificate remains optional for portable packages. Installer
development is deferred and is not part of the current release path. Formal
releases are manual owner actions; CI continues to test source and compliance
changes but does not build or publish Windows artifacts.

GitHub Actions uses path-scoped checks to limit hosted-runner consumption.
Changes to `src/`, `tests/`, or the locked Python environment run the automated
test suite on Linux with the frozen CPU extra. Dependency, container, or legal
artifact changes separately run the license policy and Python package-content
checks. Pull requests always report one required `PR Gate` result: a lightweight
job detects changed paths and calls only the affected reusable checks.
Documentation-only changes therefore do not start tests or compliance work.
Repeated pushes to the same branch cancel the older run. Both checks also
support independent manual runs and relevant pushes to `main`. They do not
start a server, download model checkpoints, build a container, or publish a
package.

## Dependency and license verification

The committed `uv.lock` includes the reproducible CPU deployment extra. After
dependency changes, rebuild the frozen environment and regenerate the legal
artifacts from the documented Linux container baseline in
[`open-source-compliance.md`](open-source-compliance.md). Do not approve a
lock-file change with stale notices or an unreviewed license; a Windows local
environment has a different platform dependency graph and is not the release
inventory source.

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

With an explicit `--config`, TOML-relative paths and its adjacent `.env` are
resolved from the configuration directory. Test configuration precedence as
CLI > process environment > adjacent `.env` > TOML > defaults. Model download
tests must inject a fake downloader and must not access ModelScope.

## Change Checklist

- Preserve the compact OpenAI-compatible response.
- Run contract tests for both model-shaped fixtures.
- Update `docs/api-contract.md` for compatible clarifications.
- Create an ADR and increment `schema_version` for breaking changes.
- Never commit recordings, model weights, API keys, or `.env` files.
