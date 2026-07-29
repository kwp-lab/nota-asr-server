from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import UploadFile


SUPPORTED_AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
COPY_CHUNK_BYTES = 1024 * 1024


class EmptyUploadError(Exception):
    pass


class UnsupportedAudioError(Exception):
    pass


class UploadTooLargeError(Exception):
    pass


async def persist_upload(
    upload: UploadFile,
    *,
    max_bytes: int,
    temp_dir: str | None,
) -> str:
    suffix = Path(upload.filename or "audio.wav").suffix.lower() or ".wav"
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise UnsupportedAudioError(suffix)

    temp_file = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="nota-asr-",
        suffix=suffix,
        dir=temp_dir,
        delete=False,
    )
    path = temp_file.name
    total = 0
    try:
        with temp_file:
            while True:
                chunk = await upload.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLargeError
                temp_file.write(chunk)
        if total == 0:
            raise EmptyUploadError
        return path
    except Exception:
        remove_file(path)
        raise
    finally:
        await upload.close()


def probe_duration(path: str) -> float:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return max(float(completed.stdout.strip()), 0.0)
    except (FileNotFoundError, ValueError, subprocess.SubprocessError):
        try:
            import soundfile as sf

            return max(float(sf.info(path).duration), 0.0)
        except Exception:
            return 0.0


def remove_file(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass

