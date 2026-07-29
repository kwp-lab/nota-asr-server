# Model Strategy

## SenseVoice Default

SenseVoice is the CPU-first default and supports Chinese, English, Japanese,
Korean, and Cantonese. The pipeline loads:

- `iic/SenseVoiceSmall` for ASR.
- `fsmn-vad` for long-audio speech segmentation.
- `cam++` for speaker embeddings and clustering.

SenseVoice inference always uses `use_itn=true`. This selects its native
`withitn` output mode, which asks SenseVoice itself to emit punctuation and
written forms for values such as dates and numbers. Nota does not load
`ct-punc` for SenseVoice. Rich tags are internal metadata and are removed by
normalization.

## Paraformer Option

The `paraformer` alias lazily loads:

- `paraformer-zh` for ASR.
- `fsmn-vad` for segmentation.
- `ct-punc` for punctuation.
- `cam++` for speaker embeddings and clustering.

Both adapters use `spk_mode=vad_segment`. This reduces model-specific sentence
boundary differences, but clients must still treat segment boundaries as
implementation details.

## Speaker Diarization

CAM++ creates an embedding for each overlapping 1.5-second speech chunk. FunASR
then clusters those embeddings and maps the resulting numeric labels back to
VAD segments. Nota converts the labels to response-local `speaker_N` values;
they are anonymous clusters, not voice identities.

FunASR 1.3.30 forces every input with fewer than 20 embeddings into one speaker,
even when `preset_spk_num` is supplied. Nota replaces that small-input branch:

- Fewer than 20 embeddings with `speaker_count`: average-linkage cosine
  clustering with the requested count, bounded by the number of embeddings.
- Fewer than 20 embeddings without `speaker_count`: average-linkage clustering
  using the upstream CAM++ merge similarity of `0.78`.
- 20 or more embeddings: the unmodified FunASR clustering backend.

This makes short multi-speaker recordings separable, but diarization remains an
estimate. Similar voices, background speech, overlapping speech, very short
turns, and poor audio can merge speakers or split one speaker into several.
Clients should let users correct labels. Supplying an accurate `speaker_count`
improves predictability but cannot exceed the number of usable speech chunks.

## Stable Output

SenseVoice and Paraformer raw results are not schema-compatible. The normalizer
maps `text`/`sentence`, millisecond timestamps, rich tags, and numeric speaker
labels to the contract in `api-contract.md`.

## Hotwords

SenseVoice does not provide decoder-level hotword biasing. This release does
not expose a hotword request field, avoiding a parameter that silently behaves
differently by model. A future design must explicitly choose decoder biasing,
audited post-processing, or a capability error per model.
