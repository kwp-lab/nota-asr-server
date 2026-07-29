# Architecture

## Request Flow

```text
Windows client
    -> FastAPI route and optional Bearer authentication
    -> bounded streaming copy to a temporary file
    -> media duration probe and policy validation
    -> ModelManager concurrency gate
    -> SenseVoiceBackend or ParaformerBackend
    -> FunASR AutoModel + FSMN-VAD + CAM++
    -> model-independent normalizer
    -> versioned API response
    -> temporary file deletion
```

## Ownership Boundaries

- API routes own HTTP validation and response selection.
- Audio storage owns bounded disk spooling, probing, and cleanup.
- ModelManager owns allowlisting, lazy loading, and inference concurrency.
- Backends own FunASR model configuration.
- The short-recording cluster adapter owns the FunASR `<20` embedding
  compatibility behavior documented in `model-strategy.md`.
- Normalization owns the public response semantics.
- Pydantic schemas are the executable API contract.

Raw FunASR dictionaries must not cross the normalization boundary.

## Concurrency

Model loading is protected by a lock. Each backend serializes calls to its
`AutoModel` instance, and the manager applies a process-wide inference
semaphore. The default is one concurrent inference because the initial target
is a CPU host and FunASR pipelines are stateful.
