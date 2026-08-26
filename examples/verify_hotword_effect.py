from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXIT_FAILED = 1
EXIT_INCONCLUSIVE = 2
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ProbeError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manually prove Nota Server hotwords with an A/B batch transcription. "
            "The normal pytest suite does not run this script."
        )
    )
    parser.add_argument("audio", type=Path, help="An Ogg recording containing the target term")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--model", choices=("paraformer", "fun-asr-nano"), default="paraformer")
    parser.add_argument(
        "--hotword",
        action="append",
        required=True,
        help="Hotword or short phrase; repeat for multiple entries",
    )
    parser.add_argument(
        "--expected",
        action="append",
        help="Expected transcript spelling; defaults to the --hotword values",
    )
    parser.add_argument("--language", default="auto")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=4 * 60 * 60)
    parser.add_argument(
        "--api-key-env",
        default="NOTA_ASR_API_KEY",
        help="Environment variable containing the client Bearer key; the key is never a CLI value",
    )
    parser.add_argument(
        "--keep-jobs",
        action="store_true",
        help="Keep both completed Server jobs instead of deleting them after comparison",
    )
    args = parser.parse_args()
    if args.poll_seconds <= 0 or args.timeout_seconds <= 0:
        parser.error("polling interval and timeout must be positive")
    return args


class Client:
    def __init__(self, base_url: str, api_key: str) -> None:
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        if not root.startswith(("http://", "https://")):
            raise ProbeError("--base-url must start with http:// or https://")
        self.root = root
        self.api_key = api_key

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 120,
    ) -> tuple[Any | None, dict[str, str]]:
        request_headers = {"Accept": "application/json", **(headers or {})}
        if self.api_key:
            request_headers["Authorization"] = f"Bearer {self.api_key}"
        data = content
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.root}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ProbeError("Server response exceeded the 16 MiB probe limit")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as error:
            raw = error.read(MAX_RESPONSE_BYTES + 1)
            code = "unknown_error"
            try:
                parsed = json.loads(raw)
                candidate = parsed.get("error", {}).get("code")
                if isinstance(candidate, str) and candidate:
                    code = candidate
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            raise ProbeError(f"{method} {path} failed with HTTP {error.code} ({code})") from error
        except URLError as error:
            raise ProbeError(f"Cannot reach Nota Server for {method} {path}") from error
        if not raw:
            return None, response_headers
        try:
            return json.loads(raw), response_headers
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProbeError(f"{method} {path} returned invalid JSON") from error


def validate_server(client: Client, model: str) -> int:
    capabilities, _ = client.request("GET", "/v1/nota/capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("hotword_request_version") != "1":
        raise ProbeError("Nota Server does not advertise hotword_request_version 1")
    chunk_bytes = capabilities.get("upload_chunk_bytes")
    if not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
        raise ProbeError("Nota Server returned an invalid upload_chunk_bytes value")

    models, _ = client.request("GET", "/v1/models")
    entries = models.get("data") if isinstance(models, dict) else None
    selected = next(
        (
            entry
            for entry in entries or []
            if isinstance(entry, dict) and entry.get("id") == model
        ),
        None,
    )
    hotword_capabilities = (
        selected.get("capabilities", {}).get("hotwords")
        if isinstance(selected, dict)
        else None
    )
    if not isinstance(hotword_capabilities, dict) or not hotword_capabilities.get("supported"):
        raise ProbeError(f"Model {model} does not advertise hotword support")
    return chunk_bytes


def create_and_start_job(
    client: Client,
    audio: Path,
    *,
    model: str,
    language: str,
    hotwords: list[str],
    chunk_bytes: int,
    label: str,
) -> str:
    size_bytes = audio.stat().st_size
    body, _ = client.request(
        "POST",
        "/v1/nota/transcription-jobs",
        json_body={
            "file_name": audio.name,
            "content_type": "audio/ogg",
            "size_bytes": size_bytes,
            "model": model,
            "language": language,
            "response_format": "verbose_json",
            "diarization": False,
            "speaker_count": None,
            "hotwords": hotwords,
        },
        headers={"Idempotency-Key": f"manual-hotword-{uuid.uuid4()}"},
    )
    job_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(job_id, str) or not job_id:
        raise ProbeError(f"{label} job creation response omitted id")
    print(f"{label.capitalize()} job created (job id: {job_id}).")

    offset = 0
    with audio.open("rb") as stream:
        while offset < size_bytes:
            chunk = stream.read(chunk_bytes)
            if not chunk:
                raise ProbeError(f"{label} upload ended before the declared file size")
            _empty, response_headers = client.request(
                "PATCH",
                f"/v1/nota/transcription-jobs/{job_id}/audio",
                content=chunk,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Upload-Offset": str(offset),
                    "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
                },
                timeout=10 * 60,
            )
            returned_offset = response_headers.get("upload-offset")
            try:
                next_offset = int(returned_offset or "")
            except ValueError as error:
                raise ProbeError(f"{label} upload response omitted a valid Upload-Offset") from error
            if next_offset != offset + len(chunk):
                raise ProbeError(f"{label} upload returned an unexpected Upload-Offset")
            offset = next_offset
    client.request("POST", f"/v1/nota/transcription-jobs/{job_id}/complete")
    print(f"{label.capitalize()} upload completed; transcription queued.")
    return job_id


def wait_for_result(
    client: Client,
    job_id: str,
    *,
    label: str,
    poll_seconds: float,
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    previous_state: tuple[Any, Any] | None = None
    while True:
        body, _ = client.request("GET", f"/v1/nota/transcription-jobs/{job_id}")
        if not isinstance(body, dict):
            raise ProbeError(f"{label} status response was not an object")
        state = body.get("state")
        phase = body.get("phase")
        current = (state, phase)
        if current != previous_state:
            print(f"{label.capitalize()} job state: {state}/{phase}")
            previous_state = current
        if state == "succeeded":
            result, _ = client.request("GET", f"/v1/nota/transcription-jobs/{job_id}/result")
            text = result.get("text") if isinstance(result, dict) else None
            if not isinstance(text, str):
                raise ProbeError(f"{label} result omitted transcript text")
            return text
        if state in {"failed", "cancelled"}:
            error = body.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown_error"
            raise ProbeError(f"{label} job entered terminal state {state} ({code})")
        if time.monotonic() >= deadline:
            raise ProbeError(f"Timed out waiting for {label} job {job_id}")
        time.sleep(poll_seconds)


def comparable(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def assert_effect(baseline: str, treatment: str, expected: list[str]) -> int:
    baseline_value = comparable(baseline)
    treatment_value = comparable(treatment)
    missing = 0
    unchanged = 0
    for index, value in enumerate(expected, start=1):
        needle = comparable(value)
        if not needle:
            raise ProbeError(f"Expected spelling #{index} contains no comparable characters")
        baseline_count = baseline_value.count(needle)
        treatment_count = treatment_value.count(needle)
        print(
            f"Target #{index}: baseline matches={baseline_count}, "
            f"hotword matches={treatment_count}."
        )
        if treatment_count == 0:
            missing += 1
        elif treatment_count <= baseline_count:
            unchanged += 1
    if missing:
        print("FAILED: the hotword transcription did not contain every expected spelling.")
        return EXIT_FAILED
    if unchanged:
        print(
            "INCONCLUSIVE: every expected spelling was recognized, but at least one was not "
            "improved over the baseline. Use audio whose rare term is misrecognized without hotwords."
        )
        return EXIT_INCONCLUSIVE
    print("PASSED: every expected spelling improved from baseline to the hotword transcription.")
    return 0


def run() -> int:
    args = parse_args()
    if not args.audio.is_file() or args.audio.suffix.lower() != ".ogg":
        raise ProbeError("The audio input must be an existing .ogg file")
    hotwords = [value.strip() for value in args.hotword if value.strip()]
    hotwords = list(dict.fromkeys(hotwords))
    if not hotwords:
        raise ProbeError("At least one non-empty hotword is required")
    if len(hotwords) > 500:
        raise ProbeError("Nota Server models accept at most 500 hotwords")
    if any(len(value) > 100 for value in hotwords):
        raise ProbeError("Each hotword must be no more than 100 characters")
    expected = args.expected or hotwords

    client = Client(args.base_url, os.environ.get(args.api_key_env, "").strip())
    chunk_bytes = validate_server(client, args.model)
    jobs: list[str] = []
    completed = False
    try:
        jobs.append(
            create_and_start_job(
                client,
                args.audio.resolve(),
                model=args.model,
                language=args.language,
                hotwords=[],
                chunk_bytes=chunk_bytes,
                label="baseline",
            )
        )
        jobs.append(
            create_and_start_job(
                client,
                args.audio.resolve(),
                model=args.model,
                language=args.language,
                hotwords=hotwords,
                chunk_bytes=chunk_bytes,
                label="hotword",
            )
        )
        baseline = wait_for_result(
            client,
            jobs[0],
            label="baseline",
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        treatment = wait_for_result(
            client,
            jobs[1],
            label="hotword",
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        completed = True
        return assert_effect(baseline, treatment, expected)
    finally:
        if completed and not args.keep_jobs:
            for job_id in jobs:
                try:
                    client.request("DELETE", f"/v1/nota/transcription-jobs/{job_id}")
                except ProbeError:
                    print(f"Warning: completed job {job_id} could not be deleted.", file=sys.stderr)


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print("Interrupted. Created jobs remain available for Server recovery or expiry.", file=sys.stderr)
        return 130
    except (ProbeError, OSError) as error:
        print(f"Hotword effect probe failed: {error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
