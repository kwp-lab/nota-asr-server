#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any


MODEL_ALIASES = {
    "sensevoice": "iic/SenseVoiceSmall",
    "paraformer": "paraformer-zh",
    "fun-asr-nano": "FunAudioLLM/Fun-ASR-Nano-2512",
}


def build_model_config(
    model_alias: str,
    *,
    diarization: bool,
    max_segment_ms: int,
    ncpu: int,
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "vad_model": "fsmn-vad",
        "vad_kwargs": {"max_single_segment_time": max_segment_ms},
        "ncpu": ncpu,
        "disable_update": True,
        "disable_pbar": True,
    }
    if diarization:
        common.update({"spk_model": "cam++", "spk_mode": "vad_segment"})

    if model_alias == "sensevoice":
        return {"model": MODEL_ALIASES[model_alias], **common}
    if model_alias == "paraformer":
        return {
            "model": MODEL_ALIASES[model_alias],
            "punc_model": "ct-punc",
            **common,
        }
    if model_alias == "fun-asr-nano":
        return {"model": MODEL_ALIASES[model_alias], **common}
    raise ValueError(f"Unknown model alias: {model_alias}")


def collect_text(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key in ("text", "sentence"):
            text = value.get(key)
            if isinstance(text, str):
                parts.append(text)
        if parts:
            return "\n".join(parts)
        return "\n".join(collect_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(collect_text(item) for item in value)
    return ""


def text_summary(value: Any) -> dict[str, Any]:
    text = collect_text(value)
    return {
        "text_characters": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def audio_duration_seconds(audio_path: Path) -> float:
    try:
        import soundfile as sf

        return float(sf.info(str(audio_path)).duration)
    except Exception as soundfile_error:
        if audio_path.suffix.lower() != ".wav":
            raise RuntimeError(
                "Could not determine media duration. Install soundfile or use WAV input."
            ) from soundfile_error

    import wave

    try:
        with wave.open(str(audio_path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    except Exception as wave_error:
        raise RuntimeError(f"Could not determine duration for {audio_path}") from wave_error


def synchronize(torch: Any, device: str) -> None:
    if device.startswith("xpu") and torch.xpu.is_available():
        torch.xpu.synchronize()
    elif device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.synchronize()


def release_device(torch: Any, device: str) -> None:
    gc.collect()
    if device.startswith("xpu") and torch.xpu.is_available():
        torch.xpu.empty_cache()
    elif device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.empty_cache()


def validate_device(torch: Any, device: str) -> None:
    if device == "cpu":
        return
    if device.startswith("xpu"):
        if not torch.xpu.is_available():
            raise RuntimeError(
                "PyTorch XPU is unavailable. Install the XPU wheel from "
                "https://download.pytorch.org/whl/xpu and verify the Intel GPU driver."
            )
        return
    if device.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch CUDA is unavailable.")
        return
    raise ValueError(f"Unsupported benchmark device: {device}")


def generate_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "input": str(args.audio),
        "batch_size": 1,
        "return_spk_res": args.diarization,
        "output_timestamp": True,
        "return_time_stamps": True,
    }
    if args.model in ("sensevoice", "fun-asr-nano"):
        kwargs["language"] = args.language
    if args.model == "sensevoice":
        kwargs["use_itn"] = True
    if args.diarization and args.speaker_count is not None:
        kwargs["preset_spk_num"] = args.speaker_count
    return kwargs


def timed_generate(model: Any, kwargs: dict[str, Any], torch: Any, device: str):
    synchronize(torch, device)
    started = time.perf_counter()
    output = model.generate(**kwargs)
    synchronize(torch, device)
    return time.perf_counter() - started, output


def benchmark_device(
    args: argparse.Namespace,
    *,
    device: str,
    duration: float,
    torch: Any,
) -> dict[str, Any]:
    validate_device(torch, device)

    from funasr import AutoModel

    config = build_model_config(
        args.model,
        diarization=args.diarization,
        max_segment_ms=args.max_segment_ms,
        ncpu=args.ncpu,
    )
    config["device"] = device

    load_started = time.perf_counter()
    model = AutoModel(**config)
    synchronize(torch, device)
    load_seconds = time.perf_counter() - load_started

    kwargs = generate_kwargs(args)
    warmup_seconds = []
    measured_seconds = []
    output_summary: dict[str, Any] | None = None
    try:
        for _ in range(args.warmup_runs):
            elapsed, output = timed_generate(model, kwargs, torch, device)
            warmup_seconds.append(elapsed)
            output_summary = text_summary(output)

        for _ in range(args.runs):
            elapsed, output = timed_generate(model, kwargs, torch, device)
            measured_seconds.append(elapsed)
            current_summary = text_summary(output)
            if output_summary is not None and current_summary != output_summary:
                raise RuntimeError(
                    f"Inconsistent transcription output across runs on {device}"
                )
            output_summary = current_summary
    finally:
        del model
        release_device(torch, device)

    median_seconds = statistics.median(measured_seconds)
    return {
        "device": device,
        "status": "ok",
        "load_seconds": load_seconds,
        "warmup_seconds": warmup_seconds,
        "runs_seconds": measured_seconds,
        "median_seconds": median_seconds,
        "mean_seconds": statistics.fmean(measured_seconds),
        "min_seconds": min(measured_seconds),
        "max_seconds": max(measured_seconds),
        "median_rtf": median_seconds / duration,
        "median_realtime_multiple": duration / median_seconds,
        **(output_summary or {}),
    }


def environment_summary(torch: Any) -> dict[str, Any]:
    xpu_names = []
    if torch.xpu.is_available():
        xpu_names = [
            torch.xpu.get_device_name(index) for index in range(torch.xpu.device_count())
        ]
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "xpu_available": torch.xpu.is_available(),
        "xpu_devices": xpu_names,
        "cpu_count": os.cpu_count(),
    }


def add_comparisons(report: dict[str, Any]) -> None:
    successful = {
        item["device"]: item
        for item in report["results"]
        if item.get("status") == "ok"
    }
    cpu = successful.get("cpu")
    if cpu is None:
        return
    comparisons = []
    for device, result in successful.items():
        if device == "cpu":
            continue
        comparisons.append(
            {
                "baseline": "cpu",
                "device": device,
                "median_speedup": cpu["median_seconds"] / result["median_seconds"],
                "load_time_ratio": result["load_seconds"] / cpu["load_seconds"],
            }
        )
    report["comparisons"] = comparisons


def print_report(report: dict[str, Any]) -> None:
    print(
        f"Model: {report['model']} | audio: {report['audio']['duration_seconds']:.2f}s"
    )
    print(
        f"PyTorch: {report['environment']['torch']} | "
        f"XPU available: {report['environment']['xpu_available']}"
    )
    for result in report["results"]:
        if result["status"] != "ok":
            print(f"{result['device']}: ERROR - {result['error']}")
            continue
        print(
            f"{result['device']}: load={result['load_seconds']:.3f}s, "
            f"median={result['median_seconds']:.3f}s, "
            f"RTF={result['median_rtf']:.4f}, "
            f"realtime={result['median_realtime_multiple']:.2f}x"
        )
    for comparison in report.get("comparisons", []):
        print(
            f"{comparison['device']} vs CPU: "
            f"{comparison['median_speedup']:.2f}x median speedup"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark identical FunASR inference on CPU and PyTorch accelerator "
            "devices without recording transcript content."
        )
    )
    parser.add_argument("audio", type=Path, help="Audio file to transcribe")
    parser.add_argument(
        "--model",
        choices=tuple(MODEL_ALIASES),
        default="fun-asr-nano",
        help="FunASR model pipeline to benchmark",
    )
    parser.add_argument(
        "--devices",
        nargs="+",
        default=["cpu", "xpu:0"],
        help="PyTorch devices to benchmark in sequence",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--ncpu", type=int, default=4)
    parser.add_argument("--max-segment-ms", type=int, default=30_000)
    parser.add_argument("--diarization", action="store_true")
    parser.add_argument("--speaker-count", type=int)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "models",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    if args.runs <= 0:
        parser.error("--runs must be positive")
    if args.warmup_runs < 0:
        parser.error("--warmup-runs cannot be negative")
    if args.ncpu <= 0:
        parser.error("--ncpu must be positive")
    if args.max_segment_ms <= 0:
        parser.error("--max-segment-ms must be positive")
    if args.speaker_count is not None and not args.diarization:
        parser.error("--speaker-count requires --diarization")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.audio = args.audio.expanduser().resolve()
    args.model_dir = args.model_dir.expanduser().resolve()
    if not args.audio.is_file():
        print(f"Audio file not found: {args.audio}", file=sys.stderr)
        return 2

    args.model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MODELSCOPE_CACHE"] = str(args.model_dir)

    try:
        import torch
    except ImportError:
        print(
            "PyTorch is not installed. Install the device-appropriate wheel first.",
            file=sys.stderr,
        )
        return 2

    duration = audio_duration_seconds(args.audio)
    if duration <= 0:
        print("Audio duration must be positive.", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "schema_version": 1,
        "runtime": "pytorch",
        "model": args.model,
        "model_id": MODEL_ALIASES[args.model],
        "model_dir": str(args.model_dir),
        "audio": {
            "name": args.audio.name,
            "bytes": args.audio.stat().st_size,
            "duration_seconds": duration,
        },
        "settings": {
            "devices": args.devices,
            "runs": args.runs,
            "warmup_runs": args.warmup_runs,
            "language": args.language,
            "ncpu": args.ncpu,
            "max_segment_ms": args.max_segment_ms,
            "diarization": args.diarization,
            "speaker_count": args.speaker_count,
        },
        "environment": environment_summary(torch),
        "results": [],
    }

    had_error = False
    for device in args.devices:
        print(f"Benchmarking {device}...", file=sys.stderr)
        try:
            result = benchmark_device(
                args,
                device=device,
                duration=duration,
                torch=torch,
            )
        except Exception as exc:
            had_error = True
            result = {
                "device": device,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        report["results"].append(result)

    add_comparisons(report)
    print_report(report)
    if args.json_out is not None:
        output_path = args.json_out.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON report: {output_path}")
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
