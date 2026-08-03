# ADR 0007: Expose Stateless Speaker Embedding Extraction

- Status: Accepted
- Date: 2026-08-02

## Context

CAM++ already performs anonymous speaker diarization inside the ASR pipeline.
Nota clients need embeddings to recognize user-confirmed participants across
meetings, but names and long-lived biometric records should not become server
state. Re-running full transcription solely to obtain embeddings wastes work
and couples identity management to the stable transcription response.

## Decision

Add a versioned, authenticated Nota endpoint that accepts one bounded 16 kHz
mono PCM16 WAV sample and returns one L2-normalized CAM++ embedding. Load the
speaker model lazily, share the inference concurrency gate, delete the
temporary upload after each request, and advertise the feature through Nota
capabilities.

The endpoint remains independent of `/v1/audio/transcriptions` and durable
jobs. It accepts no identity metadata and provides no enrollment, matching,
or storage API. The response includes a stable model fingerprint and vector
dimension so clients can exclude incompatible local samples.

## Consequences

- Clients can implement local participant libraries without bundling the
  PyTorch/FunASR runtime.
- Operators incur a one-time CAM++ load and bounded extra inference work only
  when users explicitly request identification.
- The server never becomes the authority for a person's identity.
- A later CAM++ replacement must use a new fingerprint; cross-model vectors
  are not assumed comparable.

## Alternatives Considered

- Expose diarization centroids from transcription responses. Rejected because
  it changes the stable response and ties recognition to one ASR workflow.
- Store participant profiles on the server. Rejected because it expands the
  privacy and deletion boundary.
- Require a desktop inference runtime. Rejected because it materially grows
  the client package and duplicates server model management.
