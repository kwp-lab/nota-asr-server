# Nota ASR Server

<p align="center">
  <a href="README.md">English</a> · 简体中文
</p>

Nota ASR Server 是为 Nota Windows 会议录音客户端提供语音转写能力的服务端。
它同时提供兼容 OpenAI 的转写接口和 Nota 专用的可恢复批处理协议，并把
SenseVoice、Paraformer、Fun-ASR-Nano 的输出统一为稳定的响应结构，同时使用
CAM++ 完成说话人分离。

## 当前支持范围

- 转写已经录制完成的会议；当前版本不提供实时或流式 ASR。
- 默认使用 SenseVoice，也可以按需加载 Paraformer 和 Fun-ASR-Nano。
- 提供 `speaker_0`、`speaker_1` 这类会议内说话人标签。
- Nota 任务支持断点续传，上传和推理进度可在服务重启后恢复。
- 提供兼容 OpenAI 的 `POST /v1/audio/transcriptions` 接口，支持 `json`
  和 `verbose_json` 响应。
- 支持可选的 Bearer API Key 认证。
- 默认针对 CPU 部署，同时支持在 Windows 上通过 PyTorch XPU 使用兼容的
  Intel 核显。
- 默认使用一个推理并发槽位。

## 选择 PyTorch 运行环境

| 使用目标 | PyTorch 构建 | `NOTA_DEVICE` |
| --- | --- | --- |
| 安装最简单、兼容性最好 | CPU 版 | `cpu` |
| 把推理负载转移到兼容的 Intel 核显 | XPU 版 | `xpu:0` |
| 在支持 XPU 的环境中改用 CPU | XPU 版 | `cpu` |

CPU 版 PyTorch 不能使用 XPU；XPU 版同时支持 CPU 和 XPU。因此，在 XPU
环境中只需修改 `NOTA_DEVICE` 并重启服务，就能在两个设备之间切换，不必重新
安装 PyTorch。同一个虚拟环境只能安装一种 PyTorch 构建；如果需要同时保留两种
安装，建议分别使用 `.venv` 和 `.venv-xpu`。

下面首先介绍 CPU，是因为这条默认路径对驱动和硬件的要求最少。Intel 核显是
正式支持的可选运行路径，具体步骤参见
[Windows + Intel XPU](#windows--intel-xpu)。XPU 适合降低 CPU 占用，但不保证
每个模型和每段录音都能获得更低的推理延迟。

## 快速开始：Windows + CPU

这是在本机运行服务最简单的受支持方式。不需要 Docker、独立显卡、
OpenVINO，也不要求激活 PowerShell 虚拟环境。

### 1. 准备环境

请先安装：

- Windows 11 x64；
- [Git](https://git-scm.com/download/win)；
- 64 位 [Python 3.12](https://www.python.org/downloads/windows/)；项目也支持
  Python 3.10 和 3.11；
- 首次安装 Python 依赖和下载模型所需的网络连接。

安装 Python 时可以勾选 **Add Python to PATH**，也可以直接使用下面命令中的
Python Launcher（`py`）。

### 2. 克隆仓库并创建虚拟环境

打开 PowerShell：

```powershell
git clone https://github.com/kwp-lab/nota-asr-server.git
Set-Location .\nota-asr-server

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
```

如果代码已经在本机，只需进入仓库目录，不要重复执行 `git clone`。

### 3. 安装 CPU 版 PyTorch 和服务端

先明确安装 CPU 版 PyTorch，避免 pip 隐式选择其他设备版本：

```powershell
.\.venv\Scripts\python.exe -m pip install `
  torch torchaudio --index-url https://download.pytorch.org/whl/cpu

.\.venv\Scripts\python.exe -m pip install -e .
```

这里有意使用可编辑安装。对于源码仓库，修改 Python 代码后服务会直接使用当前
代码，不需要每次重新安装整个项目。

### 4. 创建本地配置

```powershell
Copy-Item .env.example .env
```

如果服务只供这台电脑使用，请打开 `.env`，把监听地址改成：

```dotenv
NOTA_HOST=127.0.0.1
```

仓库中的示例值为 `0.0.0.0`，它适合需要由局域网中其他电脑访问的场景。
监听 `0.0.0.0` 可能会把端口暴露到网络，因此在这样做之前应配置
`NOTA_API_KEYS` 和防火墙规则。

首次运行可以继续使用其余默认值：

```dotenv
NOTA_PORT=8010
NOTA_DEVICE=cpu
NOTA_PRELOAD_MODEL=sensevoice
NOTA_ENABLED_MODELS=sensevoice,paraformer,fun-asr-nano
NOTA_MODEL_DIR=./models
NOTA_DATA_DIR=./data
NOTA_API_KEYS=
```

不要提交 `.env`，因为其中可能包含 API Key。

### 5. 启动服务

请在仓库根目录执行：

```powershell
.\.venv\Scripts\nota-asr-server.exe
```

保持这个终端窗口运行。首次启动时，FunASR 会把 SenseVoice、FSMN-VAD 和
CAM++ 下载到 `.\models`，然后加载 SenseVoice。具体时间取决于网络和 CPU，
可能需要几分钟；以后启动时会复用已经下载的文件。

请等待终端显示应用启动完成。模型加载期间 HTTP 端口可能还无法连接。如果预加载
失败，服务进程可能仍在运行，但就绪检查会返回具体的模型错误。需要停止服务时，
在这个终端中按 `Ctrl+C`。

### 6. 检查服务和模型是否就绪

打开第二个 PowerShell 窗口：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
Invoke-RestMethod http://127.0.0.1:8010/ready | ConvertTo-Json
```

第一个响应应包含 `"status": "ok"`。开始转写前，第二个响应必须包含
`"status": "ready"`。

也可以打开 [http://127.0.0.1:8010/docs](http://127.0.0.1:8010/docs)
查看交互式 API 文档。

### 7. 转写第一个音频文件

把下面的路径替换为真实的 WAV、Ogg、MP3、FLAC 或其他可由
libsndfile/FunASR 读取的音频文件。请使用 `curl.exe`，避免调用 PowerShell
历史版本中的 `curl` 别名：

```powershell
curl.exe http://127.0.0.1:8010/v1/audio/transcriptions `
  -F "file=@C:\Audio\meeting.wav" `
  -F "model=sensevoice" `
  -F "language=auto" `
  -F "response_format=verbose_json" `
  -F "diarization=true"
```

返回的 JSON 包含完整文本，以及带时间戳和会议内说话人 ID 的分段。如果已经知道
说话人数，例如三个人，可以再增加 `-F "speaker_count=3"`。

如果 `.env` 中配置了 `NOTA_API_KEYS=my-local-key`，还需要在
`curl.exe` 命令中加入：

```powershell
-H "Authorization: Bearer my-local-key"
```

## 使用 Fun-ASR-Nano

`fun-asr-nano` 默认启用，但 SenseVoice 仍是启动时预加载的模型，因此 Nano
只会在 Nota 选择它或 API 请求传入 `model=fun-asr-nano` 后懒加载。第一次使用
会下载官方、未量化的 `FunAudioLLM/Fun-ASR-Nano-2512` checkpoint，模型存储
需要超过 2 GB，随后还会把模型加载到内存。

在资源受限的主机上，可以修改 `.env`，只启用和预加载 Nano，然后重启服务：

```dotenv
NOTA_ENABLED_MODELS=fun-asr-nano
NOTA_PRELOAD_MODEL=fun-asr-nano
```

Nano 支持显式的 `zh`、`en`、`ja` 和 `yue` 语言提示。使用
`language=auto` 时，Nano 会按原始语音进行转写，但不返回可靠的语言代码，因此
稳定响应中的 `language` 为 `"und"`。Nano 使用原生标点和 ITN，由 FSMN-VAD
完成最长 30 秒的内部切段，并通过 CAM++ 进入与其他模型相同的整场会议说话人
处理链路。

本版本正式支持的 Nano 基线是 PyTorch CPU。现有 XPU 设备路径可以用于实验性
基准，但不构成 Nano 的性能或兼容性承诺。本次集成不使用 OpenVINO、vLLM、NPU
运行时或量化权重。

## Windows + Intel XPU

如果服务运行在 Windows Intel AI PC 上，而且希望把推理工作从 CPU 转移到核显，
可以使用这条路径。SenseVoice、Paraformer 和 CAM++ 已经在 Intel Arc GPU 上
通过 PyTorch XPU/FunASR 路径进行过测试；这个运行方式不使用 OpenVINO。

如果已经创建了 CPU 环境，建议保留它，并单独创建 XPU 环境：

```powershell
py -3.12 -m venv .venv-xpu
.\.venv-xpu\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-xpu\Scripts\python.exe -m pip install `
  torch torchaudio --index-url https://download.pytorch.org/whl/xpu
.\.venv-xpu\Scripts\python.exe -m pip install -e .
```

检查 PyTorch 是否能够识别 Intel 核显：

```powershell
.\.venv-xpu\Scripts\python.exe -c `
  "import torch; print(torch.__version__, torch.xpu.is_available())"
.\.venv-xpu\Scripts\python.exe -c `
  "import torch; print(torch.xpu.get_device_name(0))"
```

输出必须包含 `True` 和 Intel GPU 名称。然后修改仓库根目录下的 `.env`：

```dotenv
NOTA_DEVICE=xpu:0
```

如果 CPU 服务仍占用配置的端口，请先停止它，然后使用 XPU 环境启动：

```powershell
.\.venv-xpu\Scripts\nota-asr-server.exe
```

检查实际运行设备：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/ready | ConvertTo-Json
```

XPU 服务就绪时会返回 `"status": "ready"` 和 `"device": "xpu:0"`。如果把
`.env` 改回 `NOTA_DEVICE=cpu`，重启后同一个 XPU 环境就会改用 CPU 推理，
不需要重新安装依赖。

XPU 分流可以为录音、界面和其他服务保留更多 CPU 资源；但是对于较短或包含较多
特殊算子的任务，CPU 可能持平甚至更快。选择生产环境默认设备前，建议使用后文的
基准脚本和有代表性的会议录音进行测试。

## 连接 Nota 桌面客户端

先启动服务端，然后在 Nota 中新建或编辑 ASR Provider：

| Nota 配置项 | 本机运行时填写 |
| --- | --- |
| Provider 类型 | `FunASR` |
| API 根地址 | `http://127.0.0.1:8010/v1` |
| 模型 | `sensevoice` |
| API Key | 除非设置了 `NOTA_API_KEYS`，否则留空 |

开始转写会议前，请先使用 Nota 的连接测试。当前 Nota 客户端要求服务端支持
`batch_transcription_version=1`，可以通过下面的请求确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/v1/nota/capabilities |
  ConvertTo-Json
```

如果已经启用 API Key 认证，请在检查时携带认证信息：

```powershell
$headers = @{ Authorization = "Bearer my-local-key" }
Invoke-RestMethod `
  http://127.0.0.1:8010/v1/nota/capabilities `
  -Headers $headers |
  ConvertTo-Json
```

如果服务运行在局域网中的另一台电脑上，请将 `127.0.0.1` 换成服务端的局域网
地址，把服务端的 `NOTA_HOST` 设置为 `0.0.0.0`，在两个应用中配置相同的
API Key，并允许服务端防火墙放行 TCP 8010 端口。将服务暴露到隔离且可信的
局域网以外之前，请先阅读 [`docs/security.md`](docs/security.md)。

## Linux 快速开始

项目支持 Python 3.10–3.12。下面以 Python 3.12 为例：

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

如果服务只供本机使用，请在启动前将 `.env` 中的 `NOTA_HOST` 设置为
`127.0.0.1`。首次下载模型和就绪检查的行为与 Windows 相同。

## Docker Compose 快速开始

Docker 是本地 Python 环境之外的另一种运行方式。当前 Docker 镜像只支持 CPU。

```powershell
git clone https://github.com/kwp-lab/nota-asr-server.git
Set-Location .\nota-asr-server
docker compose up --build
```

启动后执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/ready | ConvertTo-Json
```

Compose 会把 `.\models` 和 `.\data` 挂载到容器中，因此下载的模型和未完成
任务可以在重建容器后继续保留。使用 `Ctrl+C` 停止，再通过
`docker compose up` 启动。当会议任务仍需恢复时，不要执行
`docker compose down -v`，也不要删除这两个目录。

如需启用 API Key 或使用其他宿主机端口：

```powershell
$env:NOTA_API_KEYS = "replace-with-a-long-random-value"
$env:NOTA_HOST_PORT = "9010"
docker compose up --build
```

此时服务地址为 `http://127.0.0.1:9010`。

## 配置参考

服务从环境变量和当前工作目录下的 `.env` 读取配置；环境变量优先级更高。

| 环境变量 | 默认值 | 用途 |
| --- | ---: | --- |
| `NOTA_HOST` | `0.0.0.0` | HTTP 监听地址；仅供本机使用时建议设为 `127.0.0.1`。 |
| `NOTA_PORT` | `8010` | HTTP 端口。 |
| `NOTA_DEVICE` | `cpu` | FunASR/PyTorch 设备；CPU 使用 `cpu`，XPU 版使用 `xpu:0`。 |
| `NOTA_PRELOAD_MODEL` | `sensevoice` | 服务启动时预加载的模型。 |
| `NOTA_ENABLED_MODELS` | `sensevoice,paraformer,fun-asr-nano` | API 启用的模型别名，使用英文逗号分隔。 |
| `NOTA_MODEL_DIR` | `./models` | 下载模型的缓存目录。 |
| `NOTA_DATA_DIR` | `./data` | 任务 SQLite、上传的 Ogg 和窗口检查点。 |
| `NOTA_API_KEYS` | 空 | 接受的 Bearer Token，使用英文逗号分隔；留空表示关闭认证。 |
| `NOTA_MAX_UPLOAD_BYTES` | `2147483648` | 最大上传文件大小：2 GiB。 |
| `NOTA_MAX_AUDIO_SECONDS` | `14400` | 最大录音时长：4 小时。 |
| `NOTA_MAX_CONCURRENT_INFERENCES` | `1` | 单个进程中的推理并发数。 |
| `NOTA_BATCH_UPLOAD_CHUNK_BYTES` | `8388608` | Nota 断点续传块大小：8 MiB。 |
| `NOTA_BATCH_WINDOW_SECONDS` | `300` | 内部推理窗口：5 分钟。 |
| `NOTA_BATCH_WINDOW_OVERLAP_SECONDS` | `2` | 合并相邻窗口时使用的重叠长度。 |
| `NOTA_BATCH_JOB_RETENTION_SECONDS` | `86400` | 未确认任务的保留时间：24 小时。 |
| `NOTA_SPEAKER_EMBEDDING_MAX_BYTES` | `2097152` | 说话人识别单个语音样本的最大上传大小：2 MiB。 |
| `NOTA_SPEAKER_EMBEDDING_MIN_SECONDS` | `5` | 可提取声纹的最短语音时长。 |
| `NOTA_SPEAKER_EMBEDDING_MAX_SECONDS` | `30` | 单个声纹样本的最长时长。 |
| `NOTA_TEMP_DIR` | 系统默认值 | 兼容接口使用的临时目录。 |
| `NOTA_LOG_LEVEL` | `INFO` | Python/Uvicorn 日志级别。 |

相对模型路径和数据路径会基于服务启动时的工作目录解析。除非配置了绝对路径，
否则请始终从仓库根目录启动服务。

## API 概览

### 兼容 OpenAI 的转写接口

`POST /v1/audio/transcriptions` 接收一个完整音频文件，并返回：

- `response_format=json`：`{ "text": "..." }`
- `response_format=verbose_json`：响应结构版本为 `1.0`，包含语言、音频时长、
  处理时间、带时间戳的分段和说话人 ID。

所有字段和错误响应请参见
[`docs/api-contract.md`](docs/api-contract.md)。

### Nota 可恢复批处理协议

Nota 不会把客户端的十分钟录音分块当成互相独立的 ASR 请求。它通过
`/v1/nota` 上传原始 Ogg 文件，由服务端使用有界窗口进行处理，最后再执行一次
覆盖整场会议的说话人聚类。

主要生命周期如下：

1. `GET /v1/nota/capabilities`
2. `POST /v1/nota/transcription-jobs`
3. 重复调用 `PATCH /v1/nota/transcription-jobs/{id}/audio`
4. `POST /v1/nota/transcription-jobs/{id}/complete`
5. 轮询 `GET /v1/nota/transcription-jobs/{id}`
6. `GET /v1/nota/transcription-jobs/{id}/result`
7. Nota 保存结果后调用 `DELETE /v1/nota/transcription-jobs/{id}`

上传进度、已完成窗口和结果可以在正常服务重启后恢复。客户端只有在把成功结果
写入本地 Nota 数据库后才删除远程任务；默认情况下，遗留任务会在 24 小时后
过期。

## 开发与测试

在已有虚拟环境中安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

自动化测试使用模拟模型后端，不会下载真实模型。贡献和开发流程请参见
[`docs/development.md`](docs/development.md)。

## CPU 与 Intel 核显基准测试

`scripts/benchmark_funasr.py` 会让同一个音频和模型依次在不同 PyTorch
设备上运行，并报告模型加载时间、预热后的推理延迟、实时率（RTF），以及相对于
CPU 的延迟中位数加速比。脚本不会打印转写内容，也不会把转写内容写入 JSON
报告。

XPU 基准需要安装 XPU 版 PyTorch。XPU 版也可以执行 CPU 运算，因此同一个环境
可以同时测试 `cpu` 和 `xpu:0`：

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

API 服务和基准脚本使用同一个 `fun-asr-nano` 别名。这个脚本衡量的是
PyTorch/FunASR 路径，而不是 OpenVINO。只有在希望把 CAM++ 也计入工作负载时
才添加 `--diarization`。CPU 是本版本正式支持的 Nano 基线，XPU 结果应视为
当前主机上的实验性证据。

## 常见问题

### Nano 成功返回，但 FunASR 输出 `Missing punc_model`

FunASR 1.3.30 在原生标点模型通过 `vad_segment` 使用 CAM++ 时，可能输出这条
容易误解的日志。Fun-ASR-Nano 按设计不加载 `ct-punc`；只要成功响应包含带时间戳
的 speaker 分段，结果就是有效的。真正缺少说话人结果或内部 centroid 时，Nota
任务会以 `diarization_failed` 失败，不会静默接受不可靠结果。

### `py -3.12` 提示没有安装对应的 Python

请安装 64 位 Python 3.12，或者把 `py -3.12` 换成已经安装的受支持版本，
例如 `py -3.11`。可以通过下面的命令查看：

```powershell
py --list
```

### PowerShell 阻止运行 `Activate.ps1`

本文的快速开始没有激活虚拟环境，所以不需要修改执行策略。继续使用
`.\.venv\Scripts\python.exe` 和
`.\.venv\Scripts\nota-asr-server.exe` 这样的完整命令即可。

### 第一次启动看起来一直没有完成

首次运行时，Uvicorn 完成启动前需要下载并加载多个模型。请观察服务端终端和
`.\models` 目录，不要为了绕过较慢的首次下载而同时启动多个服务进程。

### `/health` 正常，但 `/ready` 返回 HTTP 503

这表示 HTTP 进程仍然存活，但预加载模型不可用。`/ready` 响应中的 `detail`
字段会给出错误摘要，服务端终端则会显示具体的下载、依赖、模型或设备错误。
修复后重新启动服务。

### 设置 `NOTA_DEVICE=xpu:0` 后服务无法就绪

请执行 [Windows + Intel XPU](#windows--intel-xpu) 中的 XPU 检查命令，确认
安装的是 XPU 版 PyTorch、`torch.xpu.is_available()` 返回 `True`，并且
Intel 显卡驱动可以正确识别设备。同时确认启动的是 `.venv-xpu` 中的服务，而
不是只安装了 CPU 版 PyTorch 的 `.venv`。如果模型加载失败，`/ready` 响应和
服务端终端会包含对应的模型或不支持算子错误。

### 8010 端口已被占用

在 `.env` 中设置其他端口，例如 `NOTA_PORT=9010`，然后重新启动服务，并在
Nota 的 API 根地址中使用相同端口。

### Nota 无法连接局域网中的服务端

请逐项确认：

- 服务端配置了 `NOTA_HOST=0.0.0.0`；
- Nota 使用 `http://<服务端局域网地址>:8010/v1`，而不是 `127.0.0.1`；
- Windows 防火墙在预期的网络配置文件中允许 TCP 8010 入站；
- Nota 中的 API Key 与 `NOTA_API_KEYS` 中的某一个值完全一致；
- `GET /v1/nota/capabilities` 返回
  `batch_transcription_version: "1"`。

### 磁盘占用持续增长

`models` 中保存可复用的模型权重；`data` 中保存私密会议音频和持久化任务，
直到 Nota 确认删除或保留时间到期。不要把 `data` 放入日志或未经批准的普通
备份中。存储和恢复行为请参见
[`docs/operations.md`](docs/operations.md)。

## 工程文档

[`docs/README.md`](docs/README.md) 是工程文档索引，其中包括：

- 产品范围和非目标；
- 完整 API 契约；
- 架构与模型策略；
- 部署、恢复和安全说明；
- 架构决策记录。

当系统行为发生变化时，应同时更新代码、测试、README 和受到影响的技术规格。
