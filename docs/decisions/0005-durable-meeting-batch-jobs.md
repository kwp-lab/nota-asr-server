# ADR 0005: Durable Meeting-Scoped Batch Jobs

- Status: Accepted
- Date: 2026-07-30

## Context

Nota previously sent independently transcribed ten-minute files. That made
client progress resumable, but every request created a new CAM++ clustering
scope and could assign different labels to the same meeting participant.
Uploading one synchronous long request would restore the speaker scope while
losing durable progress, cancellation, and retry behavior.

## Decision

Add a Nota-specific HTTP job protocol alongside the unchanged
OpenAI-compatible endpoint. The client resumably uploads one completed Ogg
recording. The server checkpoints bounded inference windows, clusters all
speaker centroids at meeting finalization, and publishes one existing
`VerboseTranscription 1.0` response.

Jobs and offsets are stored in SQLite. A server restart requeues unfinished
inference from its last committed window. Results remain available until the
client acknowledges durable local storage, with a 24-hour expiry fallback.

## Consequences

- Speaker labels have one meeting-wide scope in Nota batch results.
- Upload and inference recovery no longer depend on partial transcripts in the
  desktop database.
- The server requires a persistent data directory and a single job scheduler
  process.
- Older servers are rejected by Nota rather than silently using inconsistent
  speaker semantics.
- This is still completed-recording batch processing, not realtime ASR.
