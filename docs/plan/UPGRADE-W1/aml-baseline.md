# AML evaluation baseline

## Adapter contract

`core/atlas/memory/aml_adapter.py` provides `MemoryAMLAdapter` with exactly two runner operations:

- `add(text, *, scope="global", meta=None) -> str` stores one entry and returns its ID.
- `search(query, k=10, *, scope=None) -> list[tuple[str, float]]` returns ranked text and score pairs.

The adapter receives an initialized Atlas `MemoryLibrary` and an optional workspace. A missing search scope delegates to Atlas's default visibility rule: global plus the current project's scope when the workspace identifies one. An explicit scope performs exact-scope retrieval. Metadata is restricted to fields supported by Atlas `Entry`; unsupported keys fail explicitly. Secret-bearing or empty text is rejected.

## First target: LoCoMo-Refined

The adapter is shaped for [LoCoMo-Refined](https://github.com/mem-eval-suite/LoCoMo_refined), whose public release documents 1,382 questions, `qa_id` identifiers, one-or-more complete acceptable answers, category labels, and evidence turn IDs. Its refined evaluator checks completeness, contradictions, unsupported details, and temporal granularity. The benchmark runner remains responsible for loading the dataset, presenting the conversation to the system, generating answers, and grading predictions; this adapter handles only the memory Add/Search boundary.

The seven-dimension profile recorded for this baseline is:

| Dimension | LoCoMo-Refined coverage / measurement |
| --- | --- |
| Fact recall | Retrieval and answer correctness for conversational facts |
| Multi-hop reasoning | Questions requiring multiple facts; report the benchmark category breakdown where available |
| Temporal reasoning | Correct time and temporal granularity under the refined judge |
| Personalization | Recall of preferences and personal details |
| Rule execution | Not directly isolated by LoCoMo-Refined; report as not measured |
| Memory governance | Not directly isolated by LoCoMo-Refined; report as not measured |
| Write/retrieval efficiency | Record write latency, retrieval latency, and retrieved item count separately from answer score |

LoCoMo-Refined does not itself define standalone rule-execution or memory-governance tasks. Those profile cells must remain `not_measured`; they must not be inferred from answer accuracy.

## Other benchmark adapters

- PersonaMem: TODO — select the supported dataset split, profile/persona schema, and official evaluation protocol before implementing an adapter.
- BEAM: TODO — select the benchmark tasks, memory-operation schema, and scoring protocol before implementing an adapter.

## Baseline status

- Adapter contract implemented; no LoCoMo-Refined dataset or evaluator is vendored in Atlas.
- No benchmark score is claimed. A score requires running a fixed dataset revision, answer model, judge model, and runner configuration and recording those versions with the result.
- `core/atlas/memory/bench.py` is unchanged.
