# ADR 0003: Preserve Diarization for Short Recordings

## Status

Accepted.

## Context

FunASR 1.3.30 returns a single speaker whenever CAM++ produces fewer than 20
embedding chunks. This branch runs before the requested speaker count is used,
so short multi-speaker meetings cannot be separated by the upstream backend.

## Decision

Wrap the FunASR cluster backend inside the Nota model adapter. For fewer than
20 embeddings, use average-linkage clustering over a precomputed cosine
distance matrix. Use `speaker_count` when provided; otherwise use the upstream
merge similarity threshold of `0.78`. Delegate inputs with at least 20
embeddings to FunASR unchanged.

Keep this behavior behind the backend boundary. The public response continues
to expose only model-independent, response-local `speaker_N` labels.

## Consequences

Short recordings can return multiple speakers and honor a known speaker count.
The threshold remains heuristic and can over-split or merge speakers. Real
two-speaker audio and synthetic clustering fixtures are required regression
checks. When upgrading FunASR, re-evaluate whether the upstream short-input
branch still exists and remove this wrapper if it becomes redundant.
