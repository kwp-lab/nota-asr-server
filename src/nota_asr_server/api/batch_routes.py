from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.concurrency import run_in_threadpool

from nota_asr_server.auth import require_api_key
from nota_asr_server.backends.speaker_embedding import (
    SPEAKER_SAMPLE_ANALYSIS_MAX_CLIP_SECONDS,
    SPEAKER_SAMPLE_ANALYSIS_MAX_FILES,
    SPEAKER_SAMPLE_ANALYSIS_MAX_TOTAL_SECONDS,
    SPEAKER_SAMPLE_ANALYSIS_MIN_CLIP_SECONDS,
    SPEAKER_SAMPLE_MIN_ACCEPTED_SECONDS,
    SPEAKER_SAMPLE_MIN_PURITY,
)
from nota_asr_server.errors import APIError
from nota_asr_server.schemas import (
    BatchCapabilities,
    CreateTranscriptionJob,
    TranscriptionJobStatus,
    VerboseTranscription,
)


router = APIRouter(prefix="/v1/nota", tags=["Nota batch transcription"])
Principal = Annotated[str, Depends(require_api_key)]


@router.get("/capabilities", response_model=BatchCapabilities)
async def capabilities(request: Request, _principal: Principal) -> BatchCapabilities:
    settings = request.app.state.settings
    return BatchCapabilities(
        upload_chunk_bytes=settings.batch_upload_chunk_bytes,
        max_upload_bytes=settings.max_upload_bytes,
        max_audio_seconds=settings.max_audio_seconds,
        audio_formats=["ogg"],
        speaker_embedding_max_bytes=settings.speaker_embedding_max_bytes,
        speaker_embedding_min_seconds=settings.speaker_embedding_min_seconds,
        speaker_embedding_max_seconds=settings.speaker_embedding_max_seconds,
        speaker_sample_analysis_max_files=SPEAKER_SAMPLE_ANALYSIS_MAX_FILES,
        speaker_sample_analysis_min_clip_seconds=(
            SPEAKER_SAMPLE_ANALYSIS_MIN_CLIP_SECONDS
        ),
        speaker_sample_analysis_max_clip_seconds=(
            SPEAKER_SAMPLE_ANALYSIS_MAX_CLIP_SECONDS
        ),
        speaker_sample_analysis_max_total_seconds=(
            SPEAKER_SAMPLE_ANALYSIS_MAX_TOTAL_SECONDS
        ),
        speaker_sample_analysis_min_accepted_seconds=(
            SPEAKER_SAMPLE_MIN_ACCEPTED_SECONDS
        ),
        speaker_sample_analysis_min_purity=SPEAKER_SAMPLE_MIN_PURITY,
    )


@router.post("/transcription-jobs", response_model=TranscriptionJobStatus, status_code=201)
async def create_job(
    request: Request,
    payload: CreateTranscriptionJob,
    principal: Principal,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TranscriptionJobStatus:
    if idempotency_key is None:
        raise APIError(
            422,
            "missing_idempotency_key",
            "Idempotency-Key header is required",
        )
    service = request.app.state.batch_jobs
    job = await run_in_threadpool(
        service.create,
        principal,
        idempotency_key,
        payload,
    )
    return service.to_status(job)


@router.patch(
    "/transcription-jobs/{job_id}/audio",
    response_model=None,
    status_code=204,
)
async def upload_audio(
    request: Request,
    job_id: str,
    principal: Principal,
    upload_offset: Annotated[int | None, Header(alias="Upload-Offset")] = None,
    upload_checksum: Annotated[str | None, Header(alias="Upload-Checksum")] = None,
) -> Response:
    if upload_offset is None or upload_offset < 0:
        raise APIError(422, "invalid_upload_offset", "Upload-Offset must be non-negative")
    if upload_checksum is None:
        raise APIError(
            422,
            "missing_upload_checksum",
            "Upload-Checksum header is required",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            length = int(declared_length)
        except ValueError as exc:
            raise APIError(422, "invalid_content_length", "Content-Length is invalid") from exc
        if length > request.app.state.settings.batch_upload_chunk_bytes:
            raise APIError(413, "upload_chunk_too_large", "Upload chunk exceeds the size limit")
    content = await request.body()
    service = request.app.state.batch_jobs
    job = await run_in_threadpool(
        service.upload,
        principal,
        job_id,
        offset=upload_offset,
        checksum=upload_checksum,
        content=content,
    )
    return Response(status_code=204, headers={"Upload-Offset": str(job.upload_offset)})


@router.post(
    "/transcription-jobs/{job_id}/complete",
    response_model=TranscriptionJobStatus,
    status_code=202,
)
async def complete_job(
    request: Request,
    job_id: str,
    principal: Principal,
) -> TranscriptionJobStatus:
    service = request.app.state.batch_jobs
    job = await run_in_threadpool(service.complete, principal, job_id)
    return service.to_status(job)


@router.get(
    "/transcription-jobs/{job_id}",
    response_model=TranscriptionJobStatus,
)
async def job_status(
    request: Request,
    job_id: str,
    principal: Principal,
) -> TranscriptionJobStatus:
    service = request.app.state.batch_jobs
    return service.to_status(service.status(principal, job_id))


@router.post(
    "/transcription-jobs/{job_id}/cancel",
    response_model=TranscriptionJobStatus,
)
async def cancel_job(
    request: Request,
    job_id: str,
    principal: Principal,
) -> TranscriptionJobStatus:
    service = request.app.state.batch_jobs
    return service.to_status(service.cancel(principal, job_id))


@router.post(
    "/transcription-jobs/{job_id}/resume",
    response_model=TranscriptionJobStatus,
)
async def resume_job(
    request: Request,
    job_id: str,
    principal: Principal,
) -> TranscriptionJobStatus:
    service = request.app.state.batch_jobs
    job = await run_in_threadpool(service.resume, principal, job_id)
    return service.to_status(job)


@router.get(
    "/transcription-jobs/{job_id}/result",
    response_model=VerboseTranscription,
)
async def job_result(
    request: Request,
    job_id: str,
    principal: Principal,
) -> VerboseTranscription:
    return request.app.state.batch_jobs.result(principal, job_id)


@router.delete(
    "/transcription-jobs/{job_id}",
    response_model=None,
    status_code=204,
)
async def delete_job(
    request: Request,
    job_id: str,
    principal: Principal,
) -> Response:
    await run_in_threadpool(request.app.state.batch_jobs.delete, principal, job_id)
    return Response(status_code=204)
