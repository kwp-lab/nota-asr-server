# Operations

## Endpoints

- `/health` proves the HTTP process is alive.
- `/ready` proves the preloaded model is ready.
- `/v1/models` lists enabled aliases and readiness.
- `/v1/nota/capabilities` advertises the durable batch protocol and limits.
- `/docs` exposes Swagger UI.

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

Model startup can take tens of seconds after a cold download. Readiness must
remain false until preload completes.

SenseVoice remains the default preload model. `fun-asr-nano` is advertised but
lazy-loaded; its first request downloads an official non-quantized checkpoint
larger than 2 GB. Hosts with limited disk or memory should set both
`NOTA_ENABLED_MODELS` and `NOTA_PRELOAD_MODEL` to `fun-asr-nano` when Nano is
the only required backend, preventing SenseVoice and Nano from remaining
resident together.

## Model Storage

`NOTA_MODEL_DIR` defaults to `./models`. At startup the service passes its
absolute path to ModelScope through `MODELSCOPE_CACHE`; FunASR then downloads
missing model snapshots below that directory. ModelScope normally defaults to
a user cache under `~/.cache/modelscope`, but Nota deliberately overrides that
SDK default so a deployment's models live with its project data.

The `models/` directory and local `.env` are ignored by Git. Back them up or
copy them separately when an offline machine must reuse downloaded weights.
With Docker Compose, `./models` is bind-mounted at `/app/models`, so downloaded
weights remain visible in the repository checkout on the host.

`NOTA_DATA_DIR` defaults to `./data` and contains the batch-job SQLite database
plus uploaded Ogg files and window checkpoints. It must be persistent across
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
