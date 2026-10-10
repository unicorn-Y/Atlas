# Third-party notices

## OpenCode edit matching logic

Source: `https://github.com/anomalyco/opencode`, `packages/opencode/src/tool/edit.ts`, commit `1ddb0873aee50d209d1a8d7f91b89c5daf692d49`. Atlas ports only the unique-anchor variable-length matching strategy; it does not include copied OpenCode source files.

```text
MIT License

Copyright (c) 2025 opencode

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Atlas Engine V1 source ports

The following files adapt code from the pinned upstream revisions listed here. Their source headers name the exact source paths and license identifiers.

- `openai/codex` commit `806d9732c974bc8a51b8317c1bd8985544fe627c` — Apache-2.0; used by `core/atlas/kernel/{edit,exec,loop,model_call,plan,repair,state,subagents,tools}.py`.
- `zai-org/ZCode` commit `29628c9acdb81b703bbd4080c207a0e7ce5e276ede` — Apache-2.0; used by `core/atlas/kernel/{context,edit,exec,loop,plan,prompt,state,subagents,tools}.py`.
- `deepseek-ai/deepseek-harness` commit `d743267388641bc76f17c45ce8b4c231aed1d32c` — MIT; used by `core/atlas/kernel/repair.py`.
- `OpenHands/software-agent-sdk` commit `1cfba2117e92730b0fe1c32520a39aad8611bb8c` — MIT; used by `core/atlas/kernel/stuck.py`.

License texts are available in the pinned upstream `LICENSE` files: [Codex](https://github.com/openai/codex/blob/806d9732c974bc8a51b8317c1bd8985544fe627c/LICENSE), [ZCode](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276ede/LICENSE), [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/LICENSE), and [OpenHands SDK](https://github.com/OpenHands/software-agent-sdk/blob/1cfba2117e92730b0fe1c32520a39aad8611bb8c/LICENSE).

## Hermes Agent

Source: `https://github.com/NousResearch/hermes-agent`, pinned through the Atlas fork at commit `aea969677c60a1bb72fe227fdfb98f196a2092cc`.

Vendored files (C5 model core, copied 2026-10-02 from the local checkout at commit
`e287231d7906bcce5bc373d20fb2e3e1e6427220`):

- `core/atlas/models/reasoning_effort.py` ← `agent/reasoning_effort.py` (verbatim copy, provenance header added).
- `core/atlas/models/models_dev.py` ← `agent/models_dev.py` (adapted: `requests` → `httpx` sync client, cache
  directory injected from `atlas.config`, `hermes_cli.config` / `hermes_constants` / `utils` helpers inlined,
  provider-plugin capability seam stubbed empty, `PROVIDER_TO_MODELS_DEV` extended with Atlas-only provider ids).

```text
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
