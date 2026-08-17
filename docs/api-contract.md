# API Contract

The public base path is `/v1`. Nota clients should request
`response_format=verbose_json` and treat `schema_version` as the contract version.

## Transcription Request

`POST /v1/audio/transcriptions` uses `multipart/form-data`.

| Field | Type | Required | Default | Meaning |
|---|---|---:|---|---|
| `file` | file | yes | - | Meeting audio |
| `model` | string | no | configured default | `sensevoice`, `paraformer`, or `fun-asr-nano` |
| `language` | string | no | `auto` | Language hint |
| `response_format` | string | no | `json` | `json`, `verbose_json`, `text`, `srt`, or `vtt` |
| `diarization` | boolean | no | `true` | Return speaker labels |
| `speaker_count` | integer | no | unknown | Optional known number of speakers, 1-64 |

## Stable Verbose Response

```json
{
  "schema_version": "1.0",
  "task": "transcribe",
  "model": "sensevoice",
  "language": "zh",
  "duration": 126.42,
  "processing_time": 8.31,
  "text": "会议完整转写内容",
  "segments": [
    {
      "id": 0,
      "start": 0.52,
      "end": 4.86,
      "text": "大家早上好，我们开始今天的会议。",
      "speaker": "speaker_0"
    }
  ]
}
```

Contract rules:

- `segments` is always an array.
- `speaker` is always present and is `null` when unavailable or disabled.
- Time values are seconds.
- `duration` is media duration; `processing_time` is server inference time.
- Language uses `zh`, `en`, `ja`, `ko`, `yue`, or `und` when undetermined.
- Fun-ASR-Nano reports `und` for `language=auto` because the checkpoint does
  not expose a reliable language code. Explicit supported hints are preserved.
- Speaker ids are only stable within one response.
- Speaker labels are diarization estimates, not verified speaker identities.
- For durable Nota batch jobs, `speaker_count` is a safety target, not an exact
  output count. Weakly similar voices are not forced together to reach it, so
  a result may contain more speakers. Invalid audio or too few usable speech
  chunks can still yield fewer speakers.
- Segment counts and boundaries may change between model implementations.

The compact `json` response remains `{"text": "..."}` for OpenAI compatibility.

## Timestamped Text Formats

`response_format` also accepts the three plain-text formats an OpenAI
transcription client already understands. They are a rendering of the same
stable response, not a second source of truth: the JSON contract stays
authoritative and no new model output is exposed.

| Format | Media type | Content |
|---|---|---|
| `text` | `text/plain; charset=utf-8` | The transcript only, identical to the `text` field |
| `srt` | `application/x-subrip; charset=utf-8` | SubRip cues numbered from 1, `HH:MM:SS,mmm` times |
| `vtt` | `text/vtt; charset=utf-8` | WebVTT cues after a `WEBVTT` header, `HH:MM:SS.mmm` times |

```srt
1
00:00:00,520 --> 00:00:04,860
speaker_0: 大家早上好，我们开始今天的会议。
```

Rendering rules:

- A cue keeps the `start` and `end` of its segment. Times are clamped at zero
  and a cue never ends before it starts.
- When a segment has a speaker label, the cue text is prefixed with
  `<speaker>: `. With `diarization=false` the cue carries the text alone.
  The label stays a meeting-local anonymous id, exactly as in the JSON contract.
- Segments whose text is empty or whitespace produce no cue, so `srt` cue
  numbering can differ from segment `id`.
- An empty transcript returns an empty `text`/`srt` body and a header-only
  `vtt` body, not an error.
- Errors keep the JSON envelope below even when a text format was requested.

## Nota Durable Batch Extension

Nota meeting clients discover `batch_transcription_version=1` at
`GET /v1/nota/capabilities`. They create an authenticated job, upload the
original Ogg sequentially with `Upload-Offset` and
`Upload-Checksum: sha256=<hex>`, finalize it, poll status, and fetch the result.

The final `GET /v1/nota/transcription-jobs/{id}/result` response is exactly the
Stable Verbose Response above. The endpoint also accepts
`?response_format=text|srt|vtt` to read the same stored result in the
timestamped text formats described above; the default stays `verbose_json` and
the stored result is unchanged. `json` is not accepted here because a durable
meeting result is never returned without its segments. A successful result read does not delete data:
the client first commits the response locally and then acknowledges cleanup
with `DELETE /v1/nota/transcription-jobs/{id}`.

The extension guarantees that speaker ids are stable across the entire final
meeting response. Upload chunks and internal processing windows are not
independent diarization scopes.

The server rejects job creation or completion with
`error.code=insufficient_storage` and HTTP 507 when the persistent data
directory cannot safely hold the upload or the bounded processing workspace.

## Nota Speaker Embedding Extension

Clients discover `speaker_embedding_version=1` at
`GET /v1/nota/capabilities`. `POST /v1/nota/speaker-embeddings` accepts an
authenticated multipart request with one `file` field. The file must be a
16 kHz mono PCM16 WAV within the advertised byte and duration limits.

```json
{
  "schema_version": "1",
  "embedding_model": "cam++",
  "embedding_fingerprint": "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1",
  "dimension": 192,
  "audio_duration": 18.4,
  "embedding": [0.012, -0.034]
}
```

The shown vector is abbreviated. The returned vector is L2-normalized. The
server deletes the temporary audio after the response and does not associate
the vector with a name, meeting, or persistent identity. Clients must compare
vectors only when both `embedding_fingerprint` and `dimension` match.

### Clean speaker sample analysis

Clients discover `speaker_sample_analysis_version=1` at the same capabilities
endpoint. `POST /v1/nota/speaker-samples/analyze` accepts repeated multipart
`files` fields containing 16 kHz mono PCM16 WAV candidates for one anonymous
transcript speaker. Limits are advertised as:

- `speaker_sample_analysis_max_files`;
- `speaker_sample_analysis_min_clip_seconds`;
- `speaker_sample_analysis_max_clip_seconds`;
- `speaker_sample_analysis_max_total_seconds`;
- `speaker_sample_analysis_min_accepted_seconds`;
- `speaker_sample_analysis_min_purity`.

The response does not change transcription data:

```json
{
  "schema_version": "1",
  "outcome": "enrollable",
  "embedding_model": "cam++",
  "embedding_fingerprint": "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1",
  "dimension": 192,
  "audio_duration": 18.0,
  "accepted_audio_duration": 11.2,
  "purity_score": 0.91,
  "preview": {"file_index": 1, "start": 0.75, "end": 6.25},
  "accepted_ranges": [
    {"file_index": 0, "start": 0.25, "end": 5.75},
    {"file_index": 1, "start": 0.75, "end": 6.45}
  ],
  "embedding": [0.012, -0.034]
}
```

`file_index` is the zero-based multipart order and times are relative seconds.
The embedding is recomputed from only the accepted dominant-speaker audio
ranges; boundary-spanning analysis windows are not enrolled.

When no sufficiently reliable reusable sample exists, the endpoint still
returns HTTP 200 so the client can offer manual listening and meeting-local
naming:

```json
{
  "schema_version": "1",
  "outcome": "preview_only",
  "embedding_model": "cam++",
  "embedding_fingerprint": "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1",
  "dimension": 0,
  "audio_duration": 18.0,
  "accepted_audio_duration": 2.8,
  "purity_score": 0.54,
  "preview": {"file_index": 1, "start": 0.25, "end": 6.0},
  "accepted_ranges": [],
  "embedding": null
}
```

`outcome=enrollable` always has a non-empty embedding and accepted ranges.
`outcome=preview_only` always has `dimension=0`, `embedding=null`, and empty
accepted ranges; its preview is not approved for biometric enrollment. HTTP
4xx is reserved for invalid or unsupported input rather than ordinary sample
quality.

## Error Response

All application and validation errors use:

```json
{
  "error": {
    "type": "invalid_request_error",
    "code": "unsupported_audio",
    "message": "Unsupported audio format",
    "request_id": "019..."
  }
}
```

Clients must branch on `error.code`, not message text.
