# DSH parity benchmark

**Status: NOT-DONE — no comparative measurements were run.** No metric below is
presented as a result. The MASTER requires one fixed task set to run against
both Atlas and DSH; the current task workspace contains neither the benchmark
runner `core/scripts/dsh_parity_bench.py` nor a verified DSH runtime adapter.
The real Atlas model round recorded in [RESULT-E](RESULT-E.md) is a live smoke
check, not a paired benchmark and must not be interpreted as one.

| Metric | Atlas | DSH | Status / blocker |
|---|---:|---:|---|
| Prompt tokens per turn | NOT-MEASURED | NOT-MEASURED | No paired fixed-task runner to normalize each runtime's usage record. |
| Tool-call rounds | NOT-MEASURED | NOT-MEASURED | No paired event collector. |
| Task wall-clock time | NOT-MEASURED | NOT-MEASURED | No paired run with the same prompts and model conditions. |
| Compaction events | NOT-MEASURED | NOT-MEASURED | No paired event collector / event mapping. |
| Retry or repair recoveries | NOT-MEASURED | NOT-MEASURED | No paired event collector / event mapping. |
| Answerable event-causality questions | NOT-MEASURED | NOT-MEASURED | Explain API exists in Atlas; a systematic parity corpus and DSH query harness are absent. |

**Owner:** coordinator/core-scripts owner should implement the paired runner,
verify the DSH checkout and runtime configuration, execute the same fixed task
set on both systems, and replace every NOT-MEASURED cell with captured values
and command/output evidence. Until that work is done, no claim that Atlas is
faster or better is supported.
