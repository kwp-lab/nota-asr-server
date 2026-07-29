#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid


def request_json(request: urllib.request.Request, timeout: float) -> dict:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def multipart_body(audio_path: Path, model: str) -> tuple[bytes, str]:
    boundary = f"----nota-smoke-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(str(audio_path))[0] or "application/octet-stream"
    parts = [
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode(),
        audio_path.read_bytes(),
        b"\r\n",
    ]
    for name, value in (
        ("model", model),
        ("response_format", "verbose_json"),
        ("diarization", "true"),
    ):
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Nota ASR Server")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--model", default="sensevoice")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    headers = {"Accept": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
    base_url = args.base_url.rstrip("/")
    try:
        for endpoint in ("/health", "/ready", "/v1/models"):
            payload = request_json(
                urllib.request.Request(base_url + endpoint, headers=headers), args.timeout
            )
            print(f"{endpoint}: {json.dumps(payload, ensure_ascii=False)}")

        body, boundary = multipart_body(args.audio, args.model)
        request_headers = dict(headers)
        request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        payload = request_json(
            urllib.request.Request(
                base_url + "/v1/audio/transcriptions",
                data=body,
                headers=request_headers,
                method="POST",
            ),
            args.timeout,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

