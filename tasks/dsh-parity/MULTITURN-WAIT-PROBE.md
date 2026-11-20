# Multi-turn context growth

Same eight-turn conversation, one word per reply, run against both
harnesses. Only accumulated history can change the prompt size.

| Turn | Atlas prompt | DSH prompt | Atlas / DSH |
|---:|---:|---:|---:|
| 1 | NOT-MEASURED | NOT-MEASURED | — |

## Run evidence

- Atlas isolated route (secrets scrubbed): `{'available': True, 'selected_model_id': 'deepseek-v4.1-flash', 'wire_model': 'deepseek-v4.1-flash', 'provider': 'openai', 'base_url': 'https://api.pleasure2ai.top/v1', 'source': 'model_manager_registry', 'credential_present': True}`
- Atlas turn 1: ok=False; final=''; session=multi-182761750; usage=partial/unknown; session_continuity=True
  - terminal=run.failed; events={'rules.loaded': 1, 'run.context.sources': 2, 'run.started': 1, 'run.status': 3, 'run.phase': 1, 'session.title': 1, 'run.failed': 1}; phases={'planning': 1, 'execution': 1}; first_waiting_type=none; failure_category=authentication

## Growth


A per-turn prompt saving that holds as history grows is worth more than
the fixed single-turn saving, because it compounds over a long session.

## Isolated backend lifecycle

- [atlas] child exit=0; forced_termination=False; graceful_lifespan=True; private_log_summary='startup=complete; shutdown=complete; errors=4; last_error_type=CancelledError'
