# T3-KERNEL-INBOX-USER-SOURCE-014

- Status: DONE_SCOPED
- Capability atom: preserve user provenance for durable next-turn prompts at the actual Kernel model-request boundary.
- Files: `core/atlas/engine/kernel/loop.py`; `core/tests/test_kernel_volatile_context_projection.py` (real AtlasRuntime + FakeLLM wire test); this batch record and capability/edge/queue/progress ledgers.
- Dependencies: durable inbox persistence and Kernel `runtime.inbox` production binding.
- Acceptance (binary): the actual FakeLLM main request contains a `next-turn` inbox message with role `user`, never `developer`; `next-step` remains the existing `developer` injection. Both entries are acknowledged only after a model request step as currently specified.
- Rollback boundary: isolated temporary SessionDB and loopback FakeLLM only; no user data/config or external model.
- Red command: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_kernel_volatile_context_projection.py::test_durable_next_turn_inbox_keeps_user_role_on_actual_model_wire --tb=short`; output `1 failed, 5 warnings in 4.36s`, exit `1`; actual FakeLLM wire contained the `next-turn` prompt as `role=developer`.
- Production now projects `next-turn` as `user` and retains `next-step` as `developer` at `AtlasKernel.run` request assembly. Actual AtlasRuntime+AgentOrchestrator+FakeLLM test asserts both roles on the provider request.
- Green combined command: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_kernel_volatile_context_projection.py tests/test_kernel_durable_inbox.py --tb=short`; output `11 passed, 5 warnings in 7.22s`, exit `0`. `py_compile` exited `0`; AST located the role expression in the direct inbox projection at `loop.py:2318`; `git diff --check` exit `0` with only existing LF→CRLF notices.
- This closes only the Kernel model-wire role mapping. App-server/SDK enqueue transport, receipt/status subscription, and automatic execution remain separate Task 3 atoms.
