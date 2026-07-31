from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "benchmark_funasr.py"
SPEC = importlib.util.spec_from_file_location("benchmark_funasr", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_nano_model_config_uses_vad_without_diarization():
    config = benchmark.build_model_config(
        "fun-asr-nano",
        diarization=False,
        max_segment_ms=15_000,
        ncpu=8,
    )

    assert config["model"] == "FunAudioLLM/Fun-ASR-Nano-2512"
    assert config["vad_model"] == "fsmn-vad"
    assert config["vad_kwargs"] == {"max_single_segment_time": 15_000}
    assert config["ncpu"] == 8
    assert "spk_model" not in config


def test_diarization_adds_the_same_speaker_pipeline_to_all_models():
    for model in benchmark.MODEL_ALIASES:
        config = benchmark.build_model_config(
            model,
            diarization=True,
            max_segment_ms=30_000,
            ncpu=4,
        )
        assert config["spk_model"] == "cam++"
        assert config["spk_mode"] == "vad_segment"


def test_text_summary_does_not_include_transcript_content():
    raw = [{"text": "private meeting transcript"}]

    summary = benchmark.text_summary(raw)

    assert summary["text_characters"] == len("private meeting transcript")
    assert summary["text_sha256"]
    assert "private meeting transcript" not in str(summary)


def test_cpu_comparison_uses_median_inference_time():
    report = {
        "results": [
            {
                "device": "cpu",
                "status": "ok",
                "median_seconds": 4.0,
                "load_seconds": 2.0,
            },
            {
                "device": "xpu:0",
                "status": "ok",
                "median_seconds": 1.0,
                "load_seconds": 3.0,
            },
        ]
    }

    benchmark.add_comparisons(report)

    assert report["comparisons"] == [
        {
            "baseline": "cpu",
            "device": "xpu:0",
            "median_speedup": 4.0,
            "load_time_ratio": 1.5,
        }
    ]
