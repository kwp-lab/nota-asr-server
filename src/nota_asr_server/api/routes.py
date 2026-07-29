from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from nota_asr_server import __version__
from nota_asr_server.auth import require_api_key
from nota_asr_server.errors import APIError, ModelLoadError, UnknownModelError
from nota_asr_server.schemas import (
    CompactTranscription,
    HealthResponse,
    ModelList,
    ReadyResponse,
    TranscriptionSegment,
    VerboseTranscription,
)
from nota_asr_server.services.audio_storage import (
    EmptyUploadError,
    UnsupportedAudioError,
    UploadTooLargeError,
    persist_upload,
    probe_duration,
    remove_file,
)


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@router.get("/ready", response_model=ReadyResponse, status_code=200)
async def ready(request: Request) -> JSONResponse:
    manager = request.app.state.model_manager
    payload = ReadyResponse(
        status="ready" if manager.ready else "not_ready",
        device=request.app.state.settings.device,
        preload_model=request.app.state.settings.preload_model,
        models_loaded=manager.loaded_models,
        detail=manager.readiness_detail,
    )
    return JSONResponse(
        status_code=200 if manager.ready else 503,
        content=payload.model_dump(),
    )


@router.get(
    "/v1/models",
    response_model=ModelList,
    dependencies=[Depends(require_api_key)],
)
async def models(request: Request) -> ModelList:
    return ModelList(data=request.app.state.model_manager.list_models())


@router.post(
    "/v1/audio/transcriptions",
    response_model=CompactTranscription | VerboseTranscription,
    dependencies=[Depends(require_api_key)],
)
async def transcribe(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    model: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "auto",
    response_format: Annotated[str, Form()] = "json",
    diarization: Annotated[bool, Form()] = True,
    speaker_count: Annotated[int | None, Form(ge=1, le=64)] = None,
) -> JSONResponse:
    settings = request.app.state.settings
    selected_model = model or settings.preload_model
    if response_format not in {"json", "verbose_json"}:
        raise APIError(
            400,
            "invalid_response_format",
            "response_format must be json or verbose_json",
        )

    temp_path = None
    try:
        temp_path = await persist_upload(
            file,
            max_bytes=settings.max_upload_bytes,
            temp_dir=settings.temp_dir,
        )
        duration = await run_in_threadpool(probe_duration, temp_path)
        if duration > settings.max_audio_seconds:
            raise APIError(
                413,
                "audio_too_long",
                f"Audio duration exceeds the {settings.max_audio_seconds} second limit",
            )

        try:
            result = await run_in_threadpool(
                request.app.state.model_manager.transcribe,
                selected_model,
                temp_path,
                language=language,
                diarization=diarization,
                speaker_count=speaker_count,
                duration=duration,
            )
        except UnknownModelError as exc:
            raise APIError(400, "model_not_found", f"Unknown model: {exc}") from exc
        except ModelLoadError as exc:
            raise APIError(
                503,
                "model_unavailable",
                f"Model is unavailable: {exc}",
                "server_error",
            ) from exc

        if response_format == "json":
            payload = CompactTranscription(text=result.text)
        else:
            payload = VerboseTranscription(
                model=selected_model,
                language=result.language,
                duration=result.duration,
                processing_time=result.processing_time,
                text=result.text,
                segments=[
                    TranscriptionSegment(
                        id=index,
                        start=segment.start,
                        end=segment.end,
                        text=segment.text,
                        speaker=segment.speaker,
                    )
                    for index, segment in enumerate(result.segments)
                ],
            )
        return JSONResponse(content=payload.model_dump())
    except UnsupportedAudioError as exc:
        raise APIError(415, "unsupported_audio", f"Unsupported audio format: {exc}") from exc
    except EmptyUploadError as exc:
        raise APIError(400, "empty_audio", "The uploaded audio file is empty") from exc
    except UploadTooLargeError as exc:
        raise APIError(413, "upload_too_large", "The uploaded file exceeds the size limit") from exc
    finally:
        remove_file(temp_path)

