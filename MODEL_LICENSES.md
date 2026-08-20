# Model licenses

Nota ASR Server downloads model snapshots at runtime. Those weights are not
part of this repository, are not covered by Nota's MIT license, and are not
included in the Python dependency SBOM. Operators must review the model card
and license for the exact revision they download.

| Runtime alias or role | Upstream model identifier | Revision | Currently declared license | License source |
|---|---|---|---|---|
| `sensevoice` | `iic/SenseVoiceSmall` | reviewed `master` snapshot | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/SenseVoiceSmall) |
| `paraformer` | `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | `v2.0.9` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) |
| Voice activity detection | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` | `v2.0.4` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch) |
| Punctuation | `iic/punc_ct-transformer_cn-en-common-vocab471067-large` | `v2.0.4` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large) |
| Speaker embeddings | `iic/speech_campplus_sv_zh-cn_16k-common` | `v2.0.2` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) |
| `fun-asr-nano` | `FunAudioLLM/Fun-ASR-Nano-2512` | reviewed `master` snapshot | Not declared by the ModelScope API at review time | [ModelScope model card](https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512) |

The default deployment stores downloaded snapshots under `models/`, which is
ignored by Git and excluded from wheels, source distributions, Docker build
contexts, and release archives. Do not publish a pre-populated model image
without separately recording every exact revision, license, required notice,
and redistribution condition.

The table was reviewed on 2026-08-18. Stable components use the listed tags.
SenseVoice and Fun-ASR-Nano have no stable release tag, so the Runtime catalog
records the reviewed upstream commit, file count, and aggregate snapshot
SHA-256 and rejects drift. This remains operational integrity metadata rather
than permission to redistribute weights. Do not redistribute Fun-ASR-Nano until
the provider publishes clear terms for that exact revision.
