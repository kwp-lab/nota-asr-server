# Business Context

Nota is a Windows client that records online meetings. The client needs a
private server endpoint that turns a completed recording into structured text
with timestamps and anonymous speaker labels.

## Product Goals

- Let the client use a familiar OpenAI-style multipart transcription request.
- Keep the response stable when the server changes ASR models.
- Support meeting review, speaker-attributed notes, and subtitle-like navigation.
- Keep customer audio inside the deployment controlled by the Nota operator.

## v0.1 Scope

The first release accepts one completed audio file and returns one completed
transcript. Nota may upload that file through the resumable `/v1/nota` job
protocol, but inference begins only after the complete recording is available.
It is not a live transcription protocol.

This boundary matters for speaker diarization. Speaker ids are clustered over
one completed recording. Internal bounded processing windows retain private
speaker centroids and are reconciled before one final response is published.
Sending independent requests to the OpenAI-compatible endpoint still creates
independent speaker scopes.

## Future Realtime Work

Realtime captions require a separate session-oriented WebSocket API with audio
chunk sequencing, partial/final results, reconnect behavior, backpressure, and
speaker embedding reconciliation across chunks. It must not be simulated by
repeated calls to the batch endpoint.
