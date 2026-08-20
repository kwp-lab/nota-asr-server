# Nota ASR Server

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a>
</p>

Nota ASR Server is the transcription service used by the Nota Windows meeting
recorder. It exposes both an OpenAI-compatible transcription endpoint and a
Nota-specific, resumable batch protocol. SenseVoice, Paraformer, and
Fun-ASR-Nano output is normalized into one stable response schema, with CAM++
speaker diarization.

## What Is Supported

- Completed meeting recordings; realtime/streaming ASR is not in the current
  scope.
- SenseVoice as the default model, with Paraformer and Fun-ASR-Nano available
  through lazy loading.
- Meeting-local speaker labels such as `speaker_0` and `speaker_1`.
- Resumable Nota jobs whose upload and inference progress survives restarts.
- `POST /v1/audio/transcriptions` with `json` and `verbose_json` responses.
- Optional Bearer API key authentication.
- CPU-first deployment plus an optional PyTorch XPU runtime for supported Intel
  GPUs on Windows.
- A locally built, movable Windows 11 x64 CPU one-folder Runtime and native
  Manager; the official ordinary-user package is CPU-only and contains no
  model weights.
- One inference slot by default.

## Standalone Windows product

Nota Client is not required to install or manage this repository. The Server
owns a standalone Windows product: a self-contained CPU Runtime and a native
Manager distributed together as a portable ZIP. Target computers need no
Python, Git, uv, Rust, Visual Studio, administrator permission, Windows
service, or `PATH` change. Models are selected and downloaded explicitly after
extraction and may be stored on another drive.

Developer/owner builds are local by design:

```powershell
.\scripts\build-windows-runtime.ps1 `
  -OutputDirectory .\dist\nota-asr-runtime `
  -PreloadModel sensevoice

.\scripts\build-windows-release.ps1 -Configuration Release
```

The first command produces an unpacked development one-folder Runtime without
the Manager. The second requires a clean worktree and formal Manager signing
configuration, then produces
`Nota-ASR-Runtime-<version>-Windows-x64-CPU.zip`. Neither command uploads an
artifact or downloads model weights. See
[`docs/operations.md`](docs/operations.md) for the CLI/configuration contract.

## Choose a PyTorch Runtime

| Goal | PyTorch build | `NOTA_DEVICE` |
| --- | --- | --- |
| Simplest and most compatible setup | CPU | `cpu` |
| Offload inference to a supported Intel GPU | XPU | `xpu:0` |
| Use CPU from an XPU-capable environment | XPU | `cpu` |

The CPU wheel cannot execute on XPU. The XPU wheel can execute on both CPU and
XPU, so an XPU environment can switch devices by changing `NOTA_DEVICE` and
restarting the server; it does not need PyTorch to be reinstalled. One virtual
environment contains one PyTorch build, so use separate `.venv` and
`.venv-xpu` environments when both installations must be preserved.

The CPU instructions below are the default Quick Start because they have the
fewest driver and hardware requirements. Intel GPU inference is a supported
optional path, documented in
[Windows and Intel XPU](#windows-and-intel-xpu). It is useful for reducing CPU
load, but it is not guaranteed to reduce latency for every model or recording.

## Quick Start: Windows and CPU

This is the simplest supported way to run the service locally. It does not
require Docker, a discrete GPU, OpenVINO, or an activated PowerShell virtual
environment.

### 1. Prerequisites

Install:

- Windows 11 x64.
- [Git](https://git-scm.com/download/win).
- 64-bit [Python 3.12](https://www.python.org/downloads/windows/). Python
  3.10 and 3.11 are also supported.
- An internet connection for the initial Python package and model downloads.

When installing Python, enable **Add Python to PATH**, or use the Python
launcher (`py`) as shown below.

### 2. Clone the repository and create a virtual environment

Open PowerShell:

```powershell
git clone https://github.com/kwp-lab/nota-asr-server.git
Set-Location .\nota-asr-server

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
```

If the repository is already present, start with `Set-Location` and do not
clone it again.

### 3. Install the CPU build of PyTorch and the server

Install PyTorch first so that pip does not choose a device build implicitly:

```powershell
.\.venv\Scripts\python.exe -m pip install `
  torch torchaudio --index-url https://download.pytorch.org/whl/cpu

.\.venv\Scripts\python.exe -m pip install -e .
```

The editable install is intentional for a source checkout: server commands use
the current repository code without reinstalling after every Python edit.

### 4. Create the local configuration

```powershell
Copy-Item .env.example .env
```

For use only on this computer, open `.env` and change:

```dotenv
NOTA_HOST=127.0.0.1
```

The checked-in example uses `0.0.0.0`, which is needed when another computer on
the LAN must reach the service. Binding to `0.0.0.0` may expose the port to the
network; configure `NOTA_API_KEYS` and firewall rules before doing that.

The other defaults are sufficient for a first run:

```dotenv
NOTA_PORT=8010
NOTA_DEVICE=cpu
NOTA_DEFAULT_MODEL=sensevoice
NOTA_PRELOAD_MODEL=sensevoice
NOTA_ENABLED_MODELS=sensevoice,paraformer,fun-asr-nano
NOTA_MODEL_DIR=./models
NOTA_DATA_DIR=./data
NOTA_MODEL_DOWNLOAD_POLICY=on_demand
NOTA_API_KEYS=
```

Do not commit `.env`: it may contain an API key.

### 5. Start the server

Run this command from the repository root:

```powershell
.\.venv\Scripts\nota-asr-server.exe
```

Keep this terminal open. On the first start, FunASR downloads SenseVoice,
FSMN-VAD, and CAM++ into `.\models`, then loads SenseVoice. This can take
several minutes depending on the connection and CPU. Later starts reuse the
downloaded files.

Wait until the terminal reports that application startup is complete. The HTTP
port may not accept connections while the model is still being loaded. If
preloading fails, the process can remain alive but readiness will report the
model error. Press `Ctrl+C` in this terminal when you want to stop the service.

### 6. Verify health and model readiness

Open a second PowerShell terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
Invoke-RestMethod http://127.0.0.1:8010/ready | ConvertTo-Json
```

The first response should contain `"status": "ok"`. The second must contain
`"status": "ready"` before starting a transcription.

You can also inspect the interactive API documentation at
[http://127.0.0.1:8010/docs](http://127.0.0.1:8010/docs).

### 7. Transcribe an audio file

Replace the path below with a real WAV, Ogg, MP3, FLAC, or other format readable
by libsndfile/FunASR. Use `curl.exe`, not PowerShell's historical `curl` alias:

```powershell
curl.exe http://127.0.0.1:8010/v1/audio/transcriptions `
  -F "file=@C:\Audio\meeting.wav" `
  -F "model=sensevoice" `
  -F "language=auto" `
  -F "response_format=verbose_json" `
  -F "diarization=true"
```

The JSON response includes the complete text and timestamped segments with
meeting-local speaker IDs. To provide a known number of speakers, add, for
example, `-F "speaker_count=3"`.

If `.env` contains `NOTA_API_KEYS=my-local-key`, add:

```powershell
-H "Authorization: Bearer my-local-key"
```

to the `curl.exe` command.

## Use Fun-ASR-Nano

`fun-asr-nano` is enabled by default but is not loaded during startup while
SenseVoice remains the preload model. Select it in Nota or send
`model=fun-asr-nano` to either transcription API. The first request downloads
the official, non-quantized `FunAudioLLM/Fun-ASR-Nano-2512` checkpoint, which
requires more than 2 GB of model storage, and then loads it into memory.

On a resource-constrained host, load only Nano by changing `.env` and
restarting the service:

```dotenv
NOTA_ENABLED_MODELS=fun-asr-nano
NOTA_PRELOAD_MODEL=fun-asr-nano
```

Nano supports explicit `zh`, `en`, `ja`, and `yue` language hints. With
`language=auto`, Nano transcribes in the spoken language but does not expose a
reliable language code, so the stable response reports `language: "und"`.
Nano uses native punctuation and ITN, FSMN-VAD for segments up to 30 seconds,
and CAM++ for the same meeting-wide speaker workflow as the other models.

PyTorch CPU is the supported Nano baseline in this release. The existing XPU
device path can be benchmarked experimentally, but is not a performance or
compatibility guarantee for Nano. This integration does not use OpenVINO,
vLLM, an NPU runtime, or quantized weights.

## Windows and Intel XPU

Use this path on a Windows Intel AI PC when moving inference work away from the
CPU is more important than using the simplest environment. SenseVoice,
Paraformer, and CAM++ have been exercised through the PyTorch XPU/FunASR path
on an Intel Arc GPU. OpenVINO is not used by this runtime.

If a CPU environment already exists, keep it and create a separate XPU
environment:

```powershell
py -3.12 -m venv .venv-xpu
.\.venv-xpu\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-xpu\Scripts\python.exe -m pip install `
  torch torchaudio --index-url https://download.pytorch.org/whl/xpu
.\.venv-xpu\Scripts\python.exe -m pip install -e .
```

Verify that PyTorch can see the Intel GPU:

```powershell
.\.venv-xpu\Scripts\python.exe -c `
  "import torch; print(torch.__version__, torch.xpu.is_available())"
.\.venv-xpu\Scripts\python.exe -c `
  "import torch; print(torch.xpu.get_device_name(0))"
```

The output must report `True` and show the Intel GPU name. Then set the device
in the repository-root `.env`:

```dotenv
NOTA_DEVICE=xpu:0
```

Stop any CPU server already using the configured port, then start the XPU
environment:

```powershell
.\.venv-xpu\Scripts\nota-asr-server.exe
```

Check the runtime selection:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/ready | ConvertTo-Json
```

A ready XPU service reports `"status": "ready"` and `"device": "xpu:0"`.
Changing `.env` back to `NOTA_DEVICE=cpu` makes the same XPU environment run
inference on CPU after a restart. Reinstallation is not required.

XPU offload can leave more CPU capacity for recording, UI, and other services,
but short or operator-heavy workloads may be as fast as, or faster on, CPU.
Use the benchmark below with representative meeting audio before selecting the
production default.

## Connect the Nota Desktop Client

Start the server first, then create or edit an ASR provider in Nota:

| Nota setting | Local value |
| --- | --- |
| Provider type | `FunASR` |
| Base URL | `http://127.0.0.1:8010/v1` |
| Model | `sensevoice` |
| API key | Empty, unless `NOTA_API_KEYS` is configured |

Use Nota's connection test before transcribing a meeting. Current Nota clients
require `batch_transcription_version=1`; the server advertises it through:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/v1/nota/capabilities |
  ConvertTo-Json
```

If API-key authentication is enabled, include it in this check:

```powershell
$headers = @{ Authorization = "Bearer my-local-key" }
Invoke-RestMethod `
  http://127.0.0.1:8010/v1/nota/capabilities `
  -Headers $headers |
  ConvertTo-Json
```

For a server on another LAN computer, replace `127.0.0.1` with that computer's
LAN address, set `NOTA_HOST=0.0.0.0`, configure the same API key in both
applications, and allow TCP port 8010 through the server firewall. Read
[`docs/security.md`](docs/security.md) before exposing the service beyond an
isolated, trusted network.

## Linux Quick Start

Python 3.10-3.12 is supported. The following example uses Python 3.12:

```bash
git clone https://github.com/kwp-lab/nota-asr-server.git
cd nota-asr-server

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install \
  torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e .

cp .env.example .env
.venv/bin/nota-asr-server
```

For a local-only service, set `NOTA_HOST=127.0.0.1` in `.env` before starting
it. The first model download and readiness behavior are the same as on Windows.

## Docker Compose Quick Start

Docker is an alternative to the local Python environment. The current image is
CPU-only.

```powershell
git clone https://github.com/kwp-lab/nota-asr-server.git
Set-Location .\nota-asr-server
docker compose up --build
```

Then verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/ready | ConvertTo-Json
```

Compose bind-mounts `.\models` and `.\data`, so downloaded weights and
unfinished batch jobs survive container recreation. Stop with `Ctrl+C`; start
again with `docker compose up`. Do not use `docker compose down -v` or delete
these directories while a meeting job must remain recoverable.

To require an API key or publish a different host port:

```powershell
$env:NOTA_API_KEYS = "replace-with-a-long-random-value"
$env:NOTA_HOST_PORT = "9010"
docker compose up --build
```

The service is then available at `http://127.0.0.1:9010`.

## Configuration Reference

Configuration is read from environment variables and from `.env` in the
current working directory. Environment variables take precedence.

| Variable | Default | Purpose |
| --- | ---: | --- |
| `NOTA_HOST` | `0.0.0.0` | HTTP bind address. Prefer `127.0.0.1` for local-only use. |
| `NOTA_PORT` | `8010` | HTTP port. |
| `NOTA_DEVICE` | `cpu` | FunASR/PyTorch device: `cpu`, or `xpu:0` with the XPU wheel. |
| `NOTA_PRELOAD_MODEL` | `sensevoice` | Model loaded during startup. |
| `NOTA_ENABLED_MODELS` | `sensevoice,paraformer,fun-asr-nano` | Comma-separated API model aliases. |
| `NOTA_MODEL_DIR` | `./models` | Downloaded model cache. |
| `NOTA_DATA_DIR` | `./data` | SQLite jobs, uploaded Ogg files, and window checkpoints. |
| `NOTA_API_KEYS` | empty | Comma-separated accepted Bearer tokens. Empty disables authentication. |
| `NOTA_MAX_UPLOAD_BYTES` | `2147483648` | Maximum uploaded file size: 2 GiB. |
| `NOTA_MAX_AUDIO_SECONDS` | `14400` | Maximum recording duration: 4 hours. |
| `NOTA_MAX_CONCURRENT_INFERENCES` | `1` | Inference concurrency within one process. |
| `NOTA_BATCH_UPLOAD_CHUNK_BYTES` | `8388608` | Nota resumable upload chunk size: 8 MiB. |
| `NOTA_BATCH_WINDOW_SECONDS` | `300` | Internal inference window: 5 minutes. |
| `NOTA_BATCH_WINDOW_OVERLAP_SECONDS` | `2` | Overlap used to merge adjacent windows. |
| `NOTA_BATCH_JOB_RETENTION_SECONDS` | `86400` | Unacknowledged job retention: 24 hours. |
| `NOTA_SPEAKER_EMBEDDING_MAX_BYTES` | `2097152` | Maximum post-transcription voice sample upload: 2 MiB. |
| `NOTA_SPEAKER_EMBEDDING_MIN_SECONDS` | `5` | Minimum usable voice sample duration. |
| `NOTA_SPEAKER_EMBEDDING_MAX_SECONDS` | `30` | Maximum voice sample duration. |
| `NOTA_TEMP_DIR` | system default | Temporary directory for the compatible endpoint. |
| `NOTA_LOG_LEVEL` | `INFO` | Python/Uvicorn log level. |

Relative model and data paths are resolved from the directory where the server
is started. Start it from the repository root unless absolute paths are used.

## API Overview

### OpenAI-compatible endpoint

`POST /v1/audio/transcriptions` accepts one complete audio upload and returns
either:

- `response_format=json`: `{ "text": "..." }`
- `response_format=verbose_json`: schema version `1.0`, including language,
  duration, processing time, timestamped segments, and speaker IDs.

See [`docs/api-contract.md`](docs/api-contract.md) for all fields and error
responses.

### Nota resumable batch protocol

Nota does not turn its ten-minute recording chunks into independent ASR
requests. It uploads the original Ogg file through `/v1/nota`, and the server
processes bounded windows before performing one meeting-wide speaker
clustering pass.

The main lifecycle is:

1. `GET /v1/nota/capabilities`
2. `POST /v1/nota/transcription-jobs`
3. Repeated `PATCH /v1/nota/transcription-jobs/{id}/audio`
4. `POST /v1/nota/transcription-jobs/{id}/complete`
5. Poll `GET /v1/nota/transcription-jobs/{id}`
6. `GET /v1/nota/transcription-jobs/{id}/result`
7. `DELETE /v1/nota/transcription-jobs/{id}` after Nota stores the result

Uploads, completed windows, and results are durable across normal service
restarts. The client deletes a successful job only after committing its result
to the local Nota database; abandoned jobs expire after 24 hours by default.

## Development and Tests

Install the development extras into the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

The automated tests use fake model backends and do not download real model
weights. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution and
privacy rules, then [`docs/development.md`](docs/development.md) for detailed
environment guidance.

## CPU and Intel GPU Benchmark

`scripts/benchmark_funasr.py` runs the same audio and model sequentially on
PyTorch devices and reports model-load time, warm inference latency, real-time
factor (RTF), and median speedup over CPU. Transcript content is not printed or
written to the JSON report.

The XPU benchmark needs an XPU build of PyTorch. An XPU build can also execute
CPU operations, so one environment can benchmark both `cpu` and `xpu:0`:

```powershell
py -3.12 -m venv .venv-xpu
.\.venv-xpu\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-xpu\Scripts\python.exe -m pip install `
  torch torchaudio --index-url https://download.pytorch.org/whl/xpu
.\.venv-xpu\Scripts\python.exe -m pip install -e ".[dev]"

.\.venv-xpu\Scripts\python.exe .\scripts\benchmark_funasr.py `
  C:\Audio\sample.wav `
  --model fun-asr-nano `
  --devices cpu xpu:0 `
  --warmup-runs 1 `
  --runs 3 `
  --json-out .\benchmark-funasr-nano.json
```

The same `fun-asr-nano` alias is registered by the API server. The benchmark
measures the PyTorch/FunASR path, not OpenVINO. Add `--diarization` only when
CAM++ should be included in the measured workload. CPU is the supported Nano
baseline; treat XPU results as host-specific experimental evidence.

## Troubleshooting

### FunASR logs `Missing punc_model` while Nano still succeeds

FunASR 1.3.30 can emit this misleading message when native-punctuation models
use CAM++ in `vad_segment` mode. Fun-ASR-Nano intentionally does not load
`ct-punc`; a successful response with timestamped speaker segments is valid.
An actual missing-speaker or internal-centroid result fails the Nota job with
`diarization_failed` instead of being silently accepted.

### `py -3.12` reports that no matching Python is installed

Install 64-bit Python 3.12, or replace `py -3.12` with the available supported
version, for example `py -3.11`. Confirm with:

```powershell
py --list
```

### PowerShell blocks `Activate.ps1`

The Quick Start does not activate the environment and therefore does not
require changing the execution policy. Keep using explicit commands such as
`.\.venv\Scripts\python.exe` and
`.\.venv\Scripts\nota-asr-server.exe`.

### The first start appears stuck

The first run downloads and loads several models before Uvicorn finishes
startup. Watch the server terminal and the `.\models` directory. Do not start
multiple copies to work around a slow first download.

### `/health` works but `/ready` returns HTTP 503

The process is alive, but the preloaded model is unavailable. The `/ready`
response contains a `detail` field; the server terminal contains the underlying
download, dependency, model, or device error. Fix that error and restart.

### `NOTA_DEVICE=xpu:0` does not become ready

Run the XPU verification command from
[Windows and Intel XPU](#windows-and-intel-xpu). Confirm that the installed
PyTorch version is an XPU build, `torch.xpu.is_available()` returns `True`, and
the Intel graphics driver exposes a device. Also confirm that the server was
started with `.venv-xpu`, not the CPU-only `.venv`. The `/ready` response and
server terminal contain the model or unsupported-operator error when model
loading fails.

### Port 8010 is already in use

Set another value in `.env`, for example `NOTA_PORT=9010`, restart the server,
and use the same port in Nota's Base URL.

### Nota cannot connect from another computer

Confirm all of the following:

- `NOTA_HOST=0.0.0.0`
- Nota uses `http://<server-lan-ip>:8010/v1`, not `127.0.0.1`
- Windows Firewall allows inbound TCP 8010 on the intended network profile
- Nota's API key exactly matches one value in `NOTA_API_KEYS`
- `GET /v1/nota/capabilities` returns `batch_transcription_version: "1"`

### Disk usage keeps growing

`models` contains reusable model weights. `data` contains private meeting audio
and durable jobs until Nota acknowledges deletion or the retention timer
expires. Do not place `data` in logs or ordinary backups. See
[`docs/operations.md`](docs/operations.md) for storage and recovery behavior.

## Documentation

[`docs/README.md`](docs/README.md) is the engineering documentation index. It
links to:

- product scope and non-goals;
- the complete API contract;
- architecture and model strategy;
- deployment, recovery, and security guidance;
- architectural decision records.

When behavior changes, update the code, tests, README, and affected technical
specification together.

## License

Nota ASR Server is licensed under the [MIT License](LICENSE). Copyright (c) 2026 kwp-lab.
Third-party Python packages retain their own licenses; see the
[dependency inventory](THIRD_PARTY_LICENSES.md), [complete notices](THIRD_PARTY_NOTICES.txt),
[CycloneDX SBOM](bom.cyclonedx.json), and [model license guidance](MODEL_LICENSES.md).
