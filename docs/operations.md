# Operations

## Endpoints

- `/health` proves the HTTP process is alive.
- `/ready` proves the preloaded model is ready.
- `/v1/models` lists enabled aliases and readiness.
- `/v1/nota/capabilities` advertises the durable batch protocol and limits.
- `/v1/nota/speaker-embeddings` performs authenticated, stateless CAM++
  extraction for a bounded client-prepared WAV sample.
- `/v1/nota/speaker-samples/analyze` performs authenticated, stateless CAM++
  purity filtering across bounded candidate WAV samples.
- `/docs` exposes Swagger UI.

Batch hotword snapshots are retained only in the job row and follow the same
acknowledgement or expiry cleanup as uploaded audio and window state. Operators
may log model, count, and stable error code, but never the hotword array or
request body.

## Windows CPU Runtime

The supported ordinary-user Windows product is a portable x64 CPU ZIP
containing a self-contained CPython Runtime and `NotaASRManager.exe`. Users
extract one folder and run the Manager; it does not install Python, modify
`PATH`, create a firewall rule, require an administrator, or register a Windows
service. Model weights are always a separate, explicit download.

For developer builds, create a movable one-folder directory:

```powershell
.\scripts\build-windows-runtime.ps1 `
  -OutputDirectory .\dist\nota-asr-runtime `
  -PreloadModel sensevoice

.\dist\nota-asr-runtime\nota-asr.cmd doctor `
  --config .\dist\nota-asr-runtime\config\server.toml `
  --output json
```

The output deliberately contains neither Manager nor a ZIP; the release script
adds the release-built Manager and packages the complete directory. Existing
output is never overwritten. Failed builds retain their uniquely named staging
directory for diagnosis, while successful builds atomically rename staging to
the requested output.

The default Runtime build is size-pruned. uv does not eagerly compile every
Python module to `.pyc`, and the staging tree removes C/C++ headers plus `.lib`
files after dependency installation. Those files are only needed to compile
native extensions, which the supported target never does. Python source,
native `.pyd` modules, and runtime `.dll` files remain, and post-prune import
and doctor checks must pass before publication.

`config/server.toml` resolves relative paths from its own directory. A `.env`
used with an explicit config also lives beside that TOML; an unrelated working
directory `.env` is ignored. Process environment variables still override that
file, and CLI options override both. API keys remain environment/`.env` only.

The Runtime template uses `127.0.0.1:8010`, explicit model downloads, and
`../models` plus `../data`. Both roots may be replaced with absolute paths such
as `D:/NotaASR/models`. Moving or upgrading program files does not invalidate
an absolute external model root.

The CLI automation contract is:

```powershell
nota-asr.cmd serve --config <path>
nota-asr.cmd config validate --config <path>
nota-asr.cmd config show --config <path> --output json
nota-asr.cmd models list --config <path> --output json
nota-asr.cmd models install <alias> --config <path> --events jsonl
nota-asr.cmd models verify <alias> --config <path> --output json
nota-asr.cmd doctor --config <path> --output json
```

Machine-readable JSON and JSONL use `schema_version: 1`. `doctor` validates
configuration, directory writability and free space, Runtime versions, model
status, and port availability without loading a model. It returns a non-zero
status when an actionable check fails.

The Manager edits the same TOML with an atomic replacement and
`server.toml.backup`, preserves unknown fields/comments, and requires a Server
restart after changing its port, model root, default model, or preload model.
When editing the portable `<runtime>/config/server.toml`, directories inside
the one-folder are written relative to that TOML so saving settings does not
break later relocation; user-selected external directories remain absolute.
It can migrate installed models to an empty directory, verifies every copied
model through the Python CLI, and leaves the source directory intact. Closing
the window hides the Manager in the notification area; choosing Exit performs
a graceful stop and then enforces cleanup with a Windows Job Object. A single
left-button release on the tray icon restores and focuses the Manager window,
matching Nota Client, while right-click exclusively opens the context menu. The
Manager's live-log workspace incrementally follows
`<data_root>/logs/server.log`, retains at most 2,000 displayed lines, supports
local filtering and automatic scrolling, and hides repetitive `/health` probes
by default. “Clear display” does not truncate or delete the underlying rotating
log. “Open log directory” resolves the same configured `data_root`, creates its
`logs` child when needed, normalizes the resulting absolute path, and reports a
visible error instead of accepting an Explorer fallback. The model list appears
before settings and marks the configured preload model; the badge changes to
“已预加载” only after the Server reaches its healthy state. Settings start
collapsed and contain diagnosis alongside configuration actions. The window,
executable, and notification-area entry share one embedded M icon so Windows
surfaces do not drift apart. The header is reserved for Server lifecycle state
and its listen address; configuration, filesystem, diagnosis, download, and
other transient action feedback appears in the single-line global status bar
at the bottom of the window. That bar spans the full window width, uses only a
top divider, and reserves the entire row for left-aligned feedback.

Portable ZIP builds do not contain `.nota-installed`, so Manager defaults to
the adjacent `config/server.toml`. A future installer may create that marker;
when present, Manager defaults to `%APPDATA%\NotaASR\server.toml` even when the
EXE is launched directly. An explicit `--config` always takes precedence.

For an upgrade, extract the new version into a fresh folder. Copy the previous
`server.toml` only when its relative paths are still appropriate, or keep model
and data roots on an absolute external path so the new Runtime can reuse them.

The owner-only release command is:

```powershell
.\scripts\build-windows-release.ps1 -Configuration Release -UnsignedRelease
```

It requires a clean worktree, an empty `[Unreleased]` section, and a dated
Changelog entry matching the current version. It builds the Runtime and
Manager, produces Windows-specific Python/Rust notices and SBOMs, runs an
offline diagnostic, and creates
`Nota-ASR-Runtime-<version>-Windows-x64-CPU.zip` with a SHA-256 and release
manifest. `-UnsignedRelease` explicitly selects the supported unsigned public
portable-package policy; the manifest records `manager_signed: false` and
`signature_policy: unsigned-public`. The checksum proves byte integrity but not
publisher identity, so release notes must disclose possible Windows
unknown-publisher or SmartScreen warnings. Omit the switch only when a configured
Authenticode certificate will sign and verify the Manager. The script does not
build an installer, upload files, create a tag or release, or run in CI.

## systemd

The reference unit is `deploy/systemd/nota-asr-server.service`.

Install it as a user service:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/nota-asr-server.service ~/.config/systemd/user/
cp .env.example .env
chmod 600 .env
systemctl --user daemon-reload
systemctl --user enable --now nota-asr-server
```

The checked-in defaults bind `0.0.0.0:8010`, so authorized machines on the
LAN can use `http://<server-lan-ip>:8010`. Binding all interfaces is not an
authorization boundary. Configure `NOTA_API_KEYS` and firewall rules before
using a shared or untrusted network.

```bash
systemctl --user status nota-asr-server
journalctl --user -u nota-asr-server -f
systemctl --user restart nota-asr-server
```

Model startup can take tens of seconds after a cold load. Readiness must remain
false until preload completes. The Windows explicit-download policy never
downloads during startup; a missing preload model leaves `/health` alive and
`/ready` unavailable.

SenseVoice remains the default preload model. `fun-asr-nano` is advertised but
lazy-loaded; its first request downloads an official non-quantized checkpoint
larger than 2 GB. Hosts with limited disk or memory should set both
`NOTA_ENABLED_MODELS` and `NOTA_PRELOAD_MODEL` to `fun-asr-nano` when Nano is
the only required backend, preventing SenseVoice and Nano from remaining
resident together.

## Model Storage

Legacy source deployments use `NOTA_MODEL_DIR` (default `./models`) and the
`on_demand` policy. An installed component under `<root>/components` is always
passed to FunASR by absolute path and therefore remains usable offline without
creating a second ModelScope cache copy. Only a missing component falls back to
its pinned Hub identifier; ModelScope downloads that snapshot below the
configured model root. ModelScope normally defaults to a user cache under
`~/.cache/modelscope`, but Nota deliberately overrides that SDK default so a
deployment's models live with its project data.

Windows Runtime uses `download_policy = "explicit"`. `models install` downloads
into `<root>/.downloads`, supports the upstream downloader's resume behavior,
hashes the assembled snapshot, writes a versioned installation marker, and only
then atomically exposes it under `<root>/components`. Completed download caches
are removed so they do not permanently double disk use; interrupted staging is
kept for resume. A digest or file-count mismatch rejects mutable `master`
snapshots and instructs operators to update the Runtime catalog.

Downloaded weights are not covered by Nota's MIT license. Operators must
review [`MODEL_LICENSES.md`](../MODEL_LICENSES.md) and each exact downloaded
model revision before redistributing a populated model directory or image.

The `models/` directory and local `.env` are ignored by Git. Back them up or
copy them separately when an offline machine must reuse downloaded weights.
With Docker Compose, `./models` is bind-mounted at `/app/models`, so downloaded
weights remain visible in the repository checkout on the host.

`NOTA_DATA_DIR` defaults to `./data` and contains the batch-job SQLite database
plus uploaded Ogg files and window checkpoints. Window checkpoints include
normalized output, speaker centers, compressed float16 CAM++ traces when
available, and aligned token metadata. It must be persistent across
service restarts. Docker Compose bind-mounts `./data` at `/app/data`.

Clients delete jobs after committing results locally. Jobs that are not
acknowledged are removed after `NOTA_BATCH_JOB_RETENTION_SECONDS` (24 hours by
default). Monitor this directory for free space; never include it in ordinary
application logs or backups that are not approved to contain meeting data.
New uploads and queue admission fail with HTTP 507 before the server exhausts
the space reserved for the recording and one processing window.

User services normally start when that user logs in. A host administrator may
enable lingering with `loginctl enable-linger <user>` when the service must
start at boot before an interactive login.

## Capacity

CPU inference defaults to one concurrent request. Queueing occurs inside one
process. Scale only after measuring representative long meetings; multiple
workers duplicate model memory and do not share the in-process semaphore.

PyTorch CPU is the supported Fun-ASR-Nano baseline. A configured XPU device is
experimental for Nano and must be benchmarked on the target Intel host; it
must not be assumed to reduce latency. OpenVINO and NPU execution are not part
of this runtime.

The service streams uploads to disk, but the reverse proxy must also enforce a
request body limit and timeout. Monitor free disk space in the configured temp
filesystem.

Nota batch uploads use 8 MiB PATCH requests, so proxy timeouts apply per upload
chunk rather than to the entire meeting. Polling and result requests remain
short. The job worker is process-local; run one Uvicorn process because multiple
workers duplicate models and job schedulers.

During graceful shutdown, the worker finishes and checkpoints its current
bounded window before SQLite is closed. Startup requeues that job and skips all
previously committed windows.
