# Architecture

## Request Flow

```text
Windows client
    -> FastAPI route and optional Bearer authentication
    -> resumable Ogg upload and SQLite job state
    -> media duration probe and policy validation after upload completion
    -> bounded five-minute 16 kHz processing windows
    -> ModelManager concurrency gate
    -> SenseVoiceBackend or ParaformerBackend
    -> FunASR AutoModel + FSMN-VAD + CAM++ speaker centroids
    -> meeting-wide centroid clustering and overlap merge
    -> model-independent normalizer
    -> versioned API response
    -> client acknowledgement or 24-hour expiry cleanup
```

## Ownership Boundaries

- API routes own HTTP validation and response selection.
- Audio storage owns bounded disk spooling, probing, and cleanup.
- The batch job service owns SQLite durability, sequential upload offsets,
  restart recovery, cancellation, processing windows, and final assembly.
- ModelManager owns allowlisting, lazy loading, and inference concurrency.
- Backends own FunASR model configuration.
- The model manager maps `NOTA_MODEL_DIR` to ModelScope's process-wide cache
  before any FunASR model is loaded.
- The short-recording cluster adapter owns the FunASR `<20` embedding
  compatibility behavior documented in `model-strategy.md`.
- Normalization owns the public response semantics.
- Pydantic schemas are the executable API contract.

Raw FunASR dictionaries must not cross the normalization boundary.

The OpenAI-compatible endpoint retains its original synchronous temporary-file
flow. The `/v1/nota` job API is additive and returns the same
`VerboseTranscription` schema only from its final result endpoint.

## Concurrency

Model loading is protected by a lock. Each backend serializes calls to its
`AutoModel` instance, and the manager applies a process-wide inference
semaphore. The default is one concurrent inference because the initial target
is a CPU host and FunASR pipelines are stateful.

The job worker commits each completed window before starting the next one.
After a restart, a processing job is requeued and resumes from its last
committed window. Cancellation is observed between windows.
