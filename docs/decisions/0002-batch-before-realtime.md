# ADR 0002: Ship Batch Transcription Before Realtime Sessions

- Status: Accepted
- Date: 2026-07-29

## Context

Nota records online meetings, but stable diarization across independently
uploaded chunks requires persistent speaker state and a session protocol.

## Decision

v0.1 accepts a complete meeting recording. Realtime transcription will use a
separate session-oriented WebSocket design.

## Consequences

The first release has predictable transcript and speaker-label semantics.
Clients cannot use repeated batch calls as a supported realtime API.

