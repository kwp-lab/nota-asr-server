# ADR 0006: Fun-ASR-Nano PyTorch CPU Baseline

- Status: Accepted
- Date: 2026-07-31

## Context

Nota needs a higher-capability ASR option without changing its stable response
or the durable meeting-wide speaker workflow. Fun-ASR-Nano is available
through the locked FunASR runtime and can produce native punctuation,
timestamps, and CAM++-compatible speaker results. OpenVINO, vLLM, NPU, and
quantized variants would introduce separate conversion, packaging, or
compatibility decisions.

## Decision

Register `fun-asr-nano` as a lazy-loaded backend backed by the official,
non-quantized `FunAudioLLM/Fun-ASR-Nano-2512` checkpoint and the existing
PyTorch/FunASR 1.3.30 runtime. Use FSMN-VAD with 30-second segments and CAM++
with `vad_segment`, then feed private centroids into the existing meeting-wide
clustering stage.

Keep SenseVoice as the preload and default model. Treat CPU as the supported
Nano baseline. Keep XPU available only for explicit target-host experiments,
and defer OpenVINO, NPU, vLLM, quantization, and hotword APIs.

Omit the model language prompt for `auto` and report `und`; translate explicit
`zh`, `en`, `ja`, and `yue` hints to Nano prompt names while preserving the
public language code.

## Consequences

- Nota discovers and selects Nano without a client or schema change.
- The first Nano request downloads more than 2 GB of model data and may leave
  both SenseVoice and Nano resident unless deployment configuration is
  narrowed.
- Nano shares the same failure policy, window recovery, centroid persistence,
  global speaker labels, and response normalization as existing backends.
- Automatic language remains honest but less specific until a separately
  evaluated language-identification design is adopted.
