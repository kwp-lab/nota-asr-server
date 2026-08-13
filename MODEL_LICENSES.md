# Model licenses

Nota ASR Server downloads model snapshots at runtime. Those weights are not
part of this repository, are not covered by Nota's MIT license, and are not
included in the Python dependency SBOM. Operators must review the model card
and license for the exact revision they download.

| Runtime alias or role | Upstream model identifier | Currently declared license | License source |
|---|---|---|---|
| `sensevoice` | `iic/SenseVoiceSmall` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/SenseVoiceSmall) |
| `paraformer` | `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) |
| Voice activity detection | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch) |
| Punctuation | `iic/punc_ct-transformer_cn-en-common-vocab471067-large` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large) |
| Speaker embeddings | `iic/speech_campplus_sv_zh-cn_16k-common` | Apache-2.0 | [ModelScope model card](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) |
| `fun-asr-nano` | `FunAudioLLM/Fun-ASR-Nano-2512` | Not declared by the ModelScope API at review time | [ModelScope model card](https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512) |

The default deployment stores downloaded snapshots under `models/`, which is
ignored by Git and excluded from wheels, source distributions, Docker build
contexts, and release archives. Do not publish a pre-populated model image
without separately recording every exact revision, license, required notice,
and redistribution condition.

The table was reviewed on 2026-08-13. The server currently requests mutable
upstream defaults for several models, so the table is informational rather than
a redistribution manifest. Re-check the actual cached snapshot revision and
its bundled license before every redistribution; do not redistribute
Fun-ASR-Nano weights until the provider publishes clear terms for that exact
revision.
