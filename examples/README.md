# Manual provider probes

Scripts in this directory perform opt-in end-to-end checks against a running
Nota ASR Server. They are deliberately outside `tests/`, so `pytest` and normal
CI never discover or execute them.

## Verify that hotwords change recognition

`verify_hotword_effect.py` submits the same Ogg recording twice through the
Nota batch API: once without hotwords and once with them. It supports
`paraformer` (decoder bias) and `fun-asr-nano` (prompt hotwords). Diarization is
disabled so the probe measures only ASR hotword behavior.

Use a short recording in which a rare name, product, or technical term is
normally misrecognized. Start the Server with the chosen model installed, then
run from the repository root:

```powershell
python .\examples\verify_hotword_effect.py `
  C:\path\to\hotword-sample.ogg `
  --model paraformer `
  --hotword "目标热词" `
  --expected "期望在转写中出现的写法"
```

If the Server requires authentication, put the matching client key in an
environment variable instead of command history:

```powershell
$env:NOTA_ASR_API_KEY = "your-local-server-key"
```

Use `--base-url http://host:port` for a non-default Server. Repeat `--hotword`
and `--expected` to check multiple terms. The script prints only job state and
match counts; it does not print or save transcript or hotword text. Completed
jobs are deleted unless `--keep-jobs` is supplied.

Exit codes intentionally distinguish evidence quality:

- `0`: every expected spelling occurs more often with hotwords than without;
- `1`: request failure, model failure, or an expected spelling is still absent;
- `2`: the expected spelling is present but the baseline was already equally
  good, so this audio cannot prove that the hotword changed recognition.
