# Model Strategy

## SenseVoice Default

SenseVoice is the CPU-first default and supports Chinese, English, Japanese,
Korean, and Cantonese. The pipeline loads:

- `iic/SenseVoiceSmall` at the cataloged `master` snapshot for ASR.
- `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` at `v2.0.4` for
  long-audio speech segmentation.
- `iic/speech_campplus_sv_zh-cn_16k-common` at `v2.0.2` for speaker
  embeddings and clustering.

SenseVoice inference always uses `use_itn=true`. This selects its native
`withitn` output mode, which asks SenseVoice itself to emit punctuation and
written forms for values such as dates and numbers. Nota does not load
`ct-punc` for SenseVoice. Rich tags are internal metadata and are removed by
normalization.

## Paraformer Option

The `paraformer` alias lazily loads:

- `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`
  at `v2.0.9` for ASR.
- FSMN-VAD at `v2.0.4` for segmentation.
- `iic/punc_ct-transformer_cn-en-common-vocab471067-large` at `v2.0.4`
  for punctuation.
- CAM++ at `v2.0.2` for speaker embeddings and clustering.

Paraformer uses `spk_mode=punc_segment`. CT-Punc first converts a long VAD
region into timestamped sentences, then FunASR assigns each sentence the
CAM++ speaker with the greatest temporal overlap. This can expose rapid
speaker changes that `vad_segment` would collapse into one label. Punctuation
errors, overlapping speech, and speaker changes within one predicted sentence
remain unresolved, so clients must treat segment boundaries as implementation
details.

## Fun-ASR-Nano Option

The `fun-asr-nano` alias lazily loads the official, non-quantized
`FunAudioLLM/Fun-ASR-Nano-2512` checkpoint together with:

- its cataloged `master` snapshot;
- FSMN-VAD at `v2.0.4`, limited to 30-second speech segments;
- CAM++ at `v2.0.2` with `spk_mode=vad_segment`.

Nano emits punctuation and inverse text normalization natively, so its
pipeline does not load `ct-punc`. The locked FunASR 1.3.30 implementation
converts Nano's dictionary-shaped character timestamps for the shared VAD and
speaker pipeline and can return `spk_embedding_center`.

Explicit `zh`, `en`, `ja`, and `yue` API hints are translated to model prompt
names. An `auto` request omits the prompt language so Nano transcribes the
spoken language, but the public result is `und` because Nano does not return a
reliable language code. Nota does not guess from the transcript or run an
additional language model.

PyTorch CPU is the supported deployment baseline. PyTorch XPU remains an
experimental device choice for Nano, and this backend does not use OpenVINO,
vLLM, an NPU runtime, remote model code, or quantized weights.

## Catalog and installation policy

`src/nota_asr_server/model_catalog.json` is the single model inventory used by
the backend resolver, CLI, Runtime resources, and Manager. It owns full model
identifiers, upstream revisions and commits, required files, reviewed license
metadata, expected download sizes, and mutable snapshot digests.

Source, Docker, and systemd deployments retain the legacy `on_demand` policy
unless they opt into explicit installation. Windows Runtime sets `explicit`:
all three aliases are visible, but startup never downloads weights. The default
and preload aliases remain `sensevoice`. Fun-ASR-Nano installation is rejected
until the caller explicitly acknowledges that its upstream license was not
declared at the catalog review date.

SenseVoice and Fun-ASR-Nano publish mutable `master` revisions. The catalog
therefore pins the reviewed upstream commit, file count, and an aggregate
SHA-256 over sorted `path`, size, and file-SHA records. A changed upstream
snapshot is treated as catalog drift, not silently accepted. Tagged components
record the digest produced at installation and re-check it on every explicit
verification.

## Speaker Diarization

CAM++ creates an embedding for each overlapping 1.5-second speech chunk with a
0.75-second shift. FunASR clusters those embeddings and initially maps the
resulting numeric labels back to VAD segments for SenseVoice and Fun-ASR-Nano,
or CT-Punc sentence boundaries for Paraformer. Nota converts the labels to
response-local `speaker_N` values; they are anonymous clusters, not voice
identities.

During window-local CAM++ clustering, FunASR 1.3.30 forces every input with
fewer than 20 embeddings into one speaker, even when `preset_spk_num` is
supplied. Nota replaces that small-input branch:

- Fewer than 20 embeddings with `speaker_count`: average-linkage cosine
  clustering with the requested count, bounded by the number of embeddings.
- Fewer than 20 embeddings without `speaker_count`: average-linkage clustering
  using the upstream CAM++ merge similarity of `0.78`.
- 20 or more embeddings: the FunASR clustering backend, with a requested count
  bounded by the available embedding count before delegation.

This makes short multi-speaker recordings separable, but diarization remains an
estimate. Similar voices, background speech, overlapping speech, very short
turns, and poor audio can merge speakers or split one speaker into several.
Clients should let users correct labels. A supplied `speaker_count` cannot
create more usable speech chunks or centroids than the audio provides.

For Nota batch jobs, FunASR returns private per-window speaker centroids through
`return_spk_center`. After every window completes, the server clusters those
sparse centroids with a separate deterministic cosine strategy; it never uses
FunASR's 20-embedding switch at the meeting level. Automatic mode uses a 0.78
similarity threshold with complete linkage so weakly related centroids cannot
enter one cluster through a similarity chain. A supplied `speaker_count` is a
safety target rather than an exact count. It uses the same 0.78 complete-linkage
safety line as automatic mode and never lowers that threshold to approach the
target. The final result may therefore contain more speakers than requested.
It may contain fewer only when there are fewer usable centers than the target.
Final clusters are renumbered by first appearance, and per-window labels never
escape in the final response. See
[`ADR 0011`](decisions/0011-separate-local-and-meeting-speaker-clustering.md).

SenseVoice and Fun-ASR-Nano batch windows additionally retain the already
computed CAM++ chunk trace and ASR token timestamps. After whole-meeting
clustering, the finalizer maps those chunks to global speaker prototypes,
requires a cosine improvement margin before reassigning a chunk, smooths turns
shorter than 0.7 seconds, and snaps stable changes to token boundaries. A split
is accepted only when the aligned tokens exactly reproduce the original
normalized segment text; otherwise the VAD segment is retained. This produces
finer speaker turns without a second model pass and never discards transcript
text. The complete flow and fallback rules are recorded in
[`ADR 0010`](decisions/0010-turn-aligned-speaker-segmentation.md).

This refinement applies only to durable whole-meeting jobs. The synchronous
OpenAI-compatible endpoint retains native model segmentation. Paraformer keeps
its CT-Punc sentence path and does not use the VAD turn refiner.

The optional `/v1/nota/speaker-embeddings` endpoint lazy-loads the same CAM++
model family independently of a selected ASR backend. It returns one
L2-normalized anonymous vector for a bounded client-prepared sample. It does
not perform name matching or participant storage.

## Stable Output

SenseVoice, Paraformer, and Fun-ASR-Nano raw results are not
schema-compatible. The normalizer maps `text`/`sentence`, millisecond
timestamps, rich tags, and numeric speaker labels to the contract in
`api-contract.md`.

## Hotwords

SenseVoice does not provide decoder-level hotword biasing. Nano accepts
prompt-based context, but that behavior is not equivalent to Paraformer's
decoder biasing. This release does not expose a hotword request field, avoiding
a parameter that silently behaves differently by model. A future design must
explicitly choose decoder biasing, prompt context, audited post-processing, or
a capability error per model.
