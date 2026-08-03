from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from nota_asr_server.auth import require_api_key
from nota_asr_server.backends.speaker_embedding import (
    SPEAKER_EMBEDDING_FINGERPRINT,
)
from nota_asr_server.errors import APIError
from nota_asr_server.schemas import SpeakerEmbeddingResponse
from nota_asr_server.services.audio_storage import (
    EmptyUploadError,
    UnsupportedAudioError,
    UploadTooLargeError,
    persist_upload,
    remove_file,
)


router = APIRouter(prefix="/v1/nota", tags=["Nota speaker identification"])


@dataclass(frozen=True)
class VoiceSampleInfo:
    duration: float


def _validate_voice_sample(path: str) -> VoiceSampleInfo:
    try:
        import soundfile as sf

        info = sf.info(path)
    except Exception as exc:
        raise APIError(
            422,
            "invalid_voice_sample",
            "The voice sample is not a decodable WAV file",
        ) from exc
    if (
        info.format != "WAV"
        or info.subtype != "PCM_16"
        or info.samplerate != 16_000
        or info.channels != 1
    ):
        raise APIError(
            422,
            "invalid_voice_sample",
            "The voice sample must be 16 kHz mono PCM16 WAV",
        )
    if info.duration <= 0:
        raise APIError(422, "invalid_voice_sample", "The voice sample is empty")
    return VoiceSampleInfo(duration=float(info.duration))


@router.post("/speaker-embeddings", response_model=SpeakerEmbeddingResponse)
async def extract_speaker_embedding(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    _principal: Annotated[str, Depends(require_api_key)],
) -> SpeakerEmbeddingResponse:
    settings = request.app.state.settings
    temp_path = None
    try:
        temp_path = await persist_upload(
            file,
            max_bytes=settings.speaker_embedding_max_bytes,
            temp_dir=settings.temp_dir,
        )
        info = await run_in_threadpool(_validate_voice_sample, temp_path)
        if info.duration < settings.speaker_embedding_min_seconds:
            raise APIError(
                422,
                "voice_sample_too_short",
                "The voice sample is shorter than the configured minimum",
            )
        if info.duration > settings.speaker_embedding_max_seconds:
            raise APIError(
                413,
                "voice_sample_too_long",
                "The voice sample exceeds the configured duration limit",
            )
        try:
            embedding = await run_in_threadpool(
                request.app.state.model_manager.extract_speaker_embedding,
                temp_path,
            )
        except Exception as exc:
            raise APIError(
                503,
                "embedding_unavailable",
                "Speaker embedding extraction is unavailable",
                "server_error",
            ) from exc
        if not embedding:
            raise APIError(
                503,
                "embedding_unavailable",
                "Speaker embedding extraction returned no vector",
                "server_error",
            )
        return SpeakerEmbeddingResponse(
            embedding_fingerprint=SPEAKER_EMBEDDING_FINGERPRINT,
            dimension=len(embedding),
            audio_duration=info.duration,
            embedding=list(embedding),
        )
    except EmptyUploadError as exc:
        raise APIError(400, "empty_audio", "The uploaded voice sample is empty") from exc
    except UnsupportedAudioError as exc:
        raise APIError(415, "unsupported_audio", "Voice samples must use WAV") from exc
    except UploadTooLargeError as exc:
        raise APIError(
            413,
            "upload_too_large",
            "The uploaded voice sample exceeds the size limit",
        ) from exc
    finally:
        remove_file(temp_path)
