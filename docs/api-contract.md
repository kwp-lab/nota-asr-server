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
| `response_format` | string | no | `json` | `json` or `verbose_json` |
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
- `speaker_count` is a clustering hint; invalid audio or too few usable speech
  chunks can still yield fewer speakers.
- Segment counts and boundaries may change between model implementations.

The compact `json` response remains `{"text": "..."}` for OpenAI compatibility.

## Nota Durable Batch Extension

Nota meeting clients discover `batch_transcription_version=1` at
`GET /v1/nota/capabilities`. They create an authenticated job, upload the
original Ogg sequentially with `Upload-Offset` and
`Upload-Checksum: sha256=<hex>`, finalize it, poll status, and fetch the result.

The final `GET /v1/nota/transcription-jobs/{id}/result` response is exactly the
Stable Verbose Response above. A successful result read does not delete data:
the client first commits the response locally and then acknowledges cleanup
with `DELETE /v1/nota/transcription-jobs/{id}`.

The extension guarantees that speaker ids are stable across the entire final
meeting response. Upload chunks and internal processing windows are not
independent diarization scopes.

The server rejects job creation or completion with
`error.code=insufficient_storage` and HTTP 507 when the persistent data
directory cannot safely hold the upload or the bounded processing workspace.

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
