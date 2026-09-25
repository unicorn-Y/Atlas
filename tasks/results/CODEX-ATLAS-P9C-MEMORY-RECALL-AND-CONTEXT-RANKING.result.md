# CODEX-ATLAS-P9C-MEMORY-RECALL-AND-CONTEXT-RANKING Result

## Delivery

- Starting `main` HEAD after `git fetch origin` and `git pull --ff-only origin main`: `fd302aa5d52b082bd5116d5788caa14baca549c4`.
- Retrieval now filters common English request words, weights fact-key matches above value matches, sorts by score and recency, and returns only matching facts within the requested limit.
- Agent context injection states that stored values are JSON user data, may be used only when relevant, and are never instructions.
- Memory approval and storage flows were not changed.

## Verification

Commands ran from `D:\Atlas\core` unless noted. Each pytest run used a fresh temporary `--basetemp` and disabled pytest's cache provider.

| Command | Result |
|---|---|
| `python -m pytest tests/test_memory.py -k 'context_' -q --no-header -p no:cacheprovider --basetemp <fresh-temp>` | 3 passed, 23 deselected |
| `python -m pytest tests/test_memory.py -q --no-header -p no:cacheprovider --basetemp <fresh-temp> --tb=short` | 25 passed, 1 known baseline failure (`TestMessages.test_message_with_metadata`, missing `metadata` field) |
| `python -m pytest tests/test_agent.py -q --no-header -p no:cacheprovider --basetemp <fresh-temp> --tb=short` | 25 passed |
| `git diff --check` | Passed; Git emitted only its standard LF-to-CRLF working-copy notices. |

The ranking regression tests produced 2 expected failures before the retrieval change: boilerplate-only terms incorrectly returned a fact, and boilerplate matches outranked a relevant fact. They pass after the change. The injection assertion also failed against the previous prompt and passed in the full agent test run.

## Ranking measurements

- Query `What language should I use?`: 1 relevant fact returned; the `favorite_language` fact ranks above matching request boilerplate.
- Query `What should I do with it?`: 0 facts returned when stored facts contain only those boilerplate terms.
- Query `What language should I use in the editor?`: 2 matching facts returned; `preferred_editor_language` ranks first.

The known metadata failure matches Issue 4 in `docs/KNOWN-BASELINE-ISSUES-2026-09-26.md`; no new memory or agent test failures were observed.
