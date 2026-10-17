# Atlas 全分支谱系与整合侦察（W0）

审查基准：`ui-redesign` `0b1ba4114e25643369c95bfac85d37563788444f`。远程分支清单来自 GitHub `unicorn-Y/Atlas/branches?per_page=100`，共 74 个；逐个验证 tip SHA 与主执行者 fetch 后的 `origin/*` 相同。分支更新时间使用 tip commit committer time 作为可复现代理；GitHub branch listing 不提供 ref 更新时间。`ahead` 表示分支独有提交数，`behind` 表示基准独有提交数。`absorbed=true` 仅表示 branch tip 是基准祖先，不证明历史功能仍有相同实现或端到端可用。

数量：74 refs = 72 distinct tip SHA / 72 distinct tree；2 组精确同 tree。37 refs 标记 absorbed（其中 36 个 tip 是基准祖先，1 个即 `ui-redesign` 自身）；36 个分叉，1 个基准后代（当前 taskbook 分支）。相对各自 merge-base 的 branch-only delta：25 个代码 ref（含一组同 SHA 重复 ref）、10 个 docs-only ref、2 个 tests-only ref。按 tip 祖先关系吸收非最大历史分支后有 22 个 maximal SHA 组 / 23 个 refs，其中 14 个是代码候选、6 个 docs-only、2 个 tests-only。此 14 是候选上限，不是最终需集成数；领域审查会排除已等价/无价值项。最大代码候选 tip 组（14）：`absorb-all`, `card-b-tc-10`, `card-c-tc-04`, `ctx-opt`, `f2-c`, `feat/personal-todos`, `fix-p1-audit`, `mem-integrate`, `memory-v1`/`memory-w1`（同一tip组）, `memory-w2-fix`, `memory-w2-ui`, `wip/c3-frontend-from-laptop`, `wip/f4-bc-20261009`, `wip/kernel-deep-research-20261015`。精确同树分支组：`main` = `docs/atlas-memory-research-20261016`（tree `3dd8eb22d14cdb1d2057691d320f9c32f1c07cd1`）；`memory-v1` = `memory-w1`（tree `d6014790fba279b5e30a10382cc84298f3dbe6d0`）。各 branch 完整 SHA、tree SHA、merge-base、ahead/behind、独有路径、line evidence、local tip 对照见 [`BRANCHES.json`](evidence/BRANCHES.json)。

## GitHub 全部分支

| Branch | Full tip SHA | Tip commit time | Merge base | Ahead / behind | 状态 | 独有模块（相对 merge-base） | 分支证据 branch@SHA:path:line |
|---|---|---|---|---:|---|---|---|
| `absorb-all` | `8d7b01d829f1332e9305fe8ee56758a6294139f7` | 2026-10-16T01:32:52+08:00 | `6bb3e10c6263e796783c11297344a7b64544a122` | 20 / 17 | 分叉 | core/atlas, core/tests, docs/parity, docs/research, frontend/src, tasks/taskbooks | `absorb-all@8d7b01d829f1332e9305fe8ee56758a6294139f7:core/atlas/agent/__init__.py:731` |
| `boot-1-core` | `efcc0cb832799d07c2c952de9d4850062c4e1cba` | 2026-10-15T03:00:25+08:00 | `efcc0cb832799d07c2c952de9d4850062c4e1cba` | 0 / 43 | 基准祖先 | 无 branch-only delta | `boot-1-core@efcc0cb832799d07c2c952de9d4850062c4e1cba:core/atlas/api/application.py:1` |
| `boot-1-int` | `67807c3aa66ea794edcc6b1f265ac70d584d64d8` | 2026-10-15T13:33:53+08:00 | `67807c3aa66ea794edcc6b1f265ac70d584d64d8` | 0 / 24 | 基准祖先 | 无 branch-only delta | `boot-1-int@67807c3aa66ea794edcc6b1f265ac70d584d64d8:tasks/reviews/BOOT-1.review.md:1` |
| `boot-1-shell` | `a157c7e2623b25db0d124ea49b087ee5648ce785` | 2026-10-15T02:36:01+08:00 | `a157c7e2623b25db0d124ea49b087ee5648ce785` | 0 / 43 | 基准祖先 | 无 branch-only delta | `boot-1-shell@a157c7e2623b25db0d124ea49b087ee5648ce785:core/atlas/desktop_entry.py:1` |
| `card-a-tc-01` | `40589104058e74c5dd8a3b04974f75dd4083a5cb` | 2026-10-12T02:30:30+08:00 | `40589104058e74c5dd8a3b04974f75dd4083a5cb` | 0 / 122 | 基准祖先 | 无 branch-only delta | `card-a-tc-01@40589104058e74c5dd8a3b04974f75dd4083a5cb:docs/parity/cards/A-TC-01.md:1` |
| `card-b-tc-02` | `07317edf817de33f4ffdbb0f1d5bd9f50c0b0c00` | 2026-10-12T12:23:36+08:00 | `07317edf817de33f4ffdbb0f1d5bd9f50c0b0c00` | 0 / 113 | 基准祖先 | 无 branch-only delta | `card-b-tc-02@07317edf817de33f4ffdbb0f1d5bd9f50c0b0c00:docs/parity/cards/B-TC-02.md:1` |
| `card-b-tc-03` | `b643e8d656406b36bb46f4c88a547358627dc2ef` | 2026-10-12T12:24:16+08:00 | `b643e8d656406b36bb46f4c88a547358627dc2ef` | 0 / 115 | 基准祖先 | 无 branch-only delta | `card-b-tc-03@b643e8d656406b36bb46f4c88a547358627dc2ef:docs/parity/cards/B-TC-03.md:1` |
| `card-b-tc-04` | `b9140952f765734f0638790b787718afb627af2c` | 2026-10-12T12:44:00+08:00 | `b9140952f765734f0638790b787718afb627af2c` | 0 / 115 | 基准祖先 | 无 branch-only delta | `card-b-tc-04@b9140952f765734f0638790b787718afb627af2c:docs/parity/cards/B-TC-04.md:1` |
| `card-b-tc-05` | `fec9552ae88cb2a753c363c4502e0c58e431356f` | 2026-10-12T11:56:34+08:00 | `fec9552ae88cb2a753c363c4502e0c58e431356f` | 0 / 116 | 基准祖先 | 无 branch-only delta | `card-b-tc-05@fec9552ae88cb2a753c363c4502e0c58e431356f:docs/parity/cards/B-TC-05.md:1` |
| `card-b-tc-06` | `076a1e5210ab76e06e8f364589b1ed2dc4766a99` | 2026-10-12T12:35:32+08:00 | `076a1e5210ab76e06e8f364589b1ed2dc4766a99` | 0 / 115 | 基准祖先 | 无 branch-only delta | `card-b-tc-06@076a1e5210ab76e06e8f364589b1ed2dc4766a99:docs/parity/cards/B-TC-06.md:1` |
| `card-b-tc-08` | `99d9b7747f0819dc9a6a84ab096d7098a5c2866f` | 2026-10-12T13:05:24+08:00 | `99d9b7747f0819dc9a6a84ab096d7098a5c2866f` | 0 / 115 | 基准祖先 | 无 branch-only delta | `card-b-tc-08@99d9b7747f0819dc9a6a84ab096d7098a5c2866f:docs/parity/cards/B-TC-08.md:1` |
| `card-b-tc-10` | `0dfc918c7bbc481f6fa99d4f697dd5fccbd7a20f` | 2026-10-12T13:42:01+08:00 | `e9be4b4b176eae332c82cd124ec669b4b7612969` | 2 / 117 | 分叉 | backend-adapter/src, core/atlas, docs/parity, frontend/src | `card-b-tc-10@0dfc918c7bbc481f6fa99d4f697dd5fccbd7a20f:backend-adapter/src/client.ts:534` |
| `card-c-tc-04` | `fba530af68422556c98d489ebe242203c3343f49` | 2026-10-12T13:11:30+08:00 | `e9be4b4b176eae332c82cd124ec669b4b7612969` | 2 / 117 | 分叉 | core/atlas, docs/parity, frontend/src | `card-c-tc-04@fba530af68422556c98d489ebe242203c3343f49:core/atlas/api/application.py:61` |
| `card-d-tc-01` | `8c8d3b7b72fd7c9a6146df63572e017863e5e854` | 2026-10-12T12:48:40+08:00 | `8c8d3b7b72fd7c9a6146df63572e017863e5e854` | 0 / 115 | 基准祖先 | 无 branch-only delta | `card-d-tc-01@8c8d3b7b72fd7c9a6146df63572e017863e5e854:docs/parity/cards/D-TC-01.md:1` |
| `card-d-tc-02` | `3442fb508742f3e68e736bb76ab4d0657007f704` | 2026-10-12T02:37:42+08:00 | `3442fb508742f3e68e736bb76ab4d0657007f704` | 0 / 122 | 基准祖先 | 无 branch-only delta | `card-d-tc-02@3442fb508742f3e68e736bb76ab4d0657007f704:docs/parity/cards/D-TC-02.md:1` |
| `card-d-tc-04` | `acc972d67f0718c36db448e9384b224fa7db6aba` | 2026-10-12T12:04:19+08:00 | `acc972d67f0718c36db448e9384b224fa7db6aba` | 0 / 122 | 基准祖先 | 无 branch-only delta | `card-d-tc-04@acc972d67f0718c36db448e9384b224fa7db6aba:docs/parity/cards/D-TC-04.md:1` |
| `ctx-opt` | `bddafde3ce6f76fb953085b89c096b68188e1ea0` | 2026-10-15T01:09:40+08:00 | `7826e91c6c71dfc180f6fad6136b5eb53a9dab52` | 1 / 46 | 分叉 | backend-adapter/src, core/atlas, core/tests, engine, frontend/src, scripts/diag, tasks/reviews | `ctx-opt@bddafde3ce6f76fb953085b89c096b68188e1ea0:backend-adapter/src/client.ts:2` |
| `docs/atlas-memory-research-20261016` | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | 2026-10-06T06:18:06+08:00 | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | 0 / 340 | 基准祖先 | 无 branch-only delta | `docs/atlas-memory-research-20261016@aa6196f550098cc46081dc6db2c376cb87ddffa5:core/pyproject.toml:1` |
| `engine-v1` | `cbd1dc2d487e324844a60da29280c8782ef3133a` | 2026-10-10T20:35:39+08:00 | `cbd1dc2d487e324844a60da29280c8782ef3133a` | 0 / 184 | 基准祖先 | 无 branch-only delta | `engine-v1@cbd1dc2d487e324844a60da29280c8782ef3133a:tasks/results/ATLAS-ENGINE-V1.result.md:1` |
| `engine-v2b` | `9a1d0feeef4ee49d2fb4b37f67f35ed227d023d8` | 2026-10-11T00:26:37+08:00 | `9a1d0feeef4ee49d2fb4b37f67f35ed227d023d8` | 0 / 173 | 基准祖先 | 无 branch-only delta | `engine-v2b@9a1d0feeef4ee49d2fb4b37f67f35ed227d023d8:tasks/results/ATLAS-ENGINE-V2-B.result.md:1` |
| `engine-v2` | `3c5e6ac5142331c7b7e6c5bd38459a7e17a3b67d` | 2026-10-10T19:28:39+08:00 | `3c5e6ac5142331c7b7e6c5bd38459a7e17a3b67d` | 0 / 184 | 基准祖先 | 无 branch-only delta | `engine-v2@3c5e6ac5142331c7b7e6c5bd38459a7e17a3b67d:tasks/results/ATLAS-ENGINE-V2-A.result.md:1` |
| `engine-v3` | `140eece4cd8765b88604b75876795214889a5744` | 2026-10-11T02:28:52+08:00 | `140eece4cd8765b88604b75876795214889a5744` | 0 / 167 | 基准祖先 | 无 branch-only delta | `engine-v3@140eece4cd8765b88604b75876795214889a5744:tasks/results/ATLAS-ENGINE-V3.result.md:1` |
| `f1-a` | `8b2a61f929faa1bee2d5d061df4eff5ba8a825b6` | 2026-10-11T12:45:17+08:00 | `8b2a61f929faa1bee2d5d061df4eff5ba8a825b6` | 0 / 162 | 基准祖先 | 无 branch-only delta | `f1-a@8b2a61f929faa1bee2d5d061df4eff5ba8a825b6:docs/parity/F1-A.md:1` |
| `f1-b` | `7ae6e1187e66ed536809caed3df888060cf03c7c` | 2026-10-11T13:03:06+08:00 | `7ae6e1187e66ed536809caed3df888060cf03c7c` | 0 / 165 | 基准祖先 | 无 branch-only delta | `f1-b@7ae6e1187e66ed536809caed3df888060cf03c7c:THIRD_PARTY_NOTICES.md:1` |
| `f1-c` | `baa9a61a632935667e3b524ea95b0beb43bad019` | 2026-10-11T16:26:06+08:00 | `baa9a61a632935667e3b524ea95b0beb43bad019` | 0 / 164 | 基准祖先 | 无 branch-only delta | `f1-c@baa9a61a632935667e3b524ea95b0beb43bad019:tasks/results/FEATURE-F1-C.result.md:1` |
| `f1-d` | `2ef6580bfd5b4c45018c2e4003751826f65cdcf9` | 2026-10-11T17:55:54+08:00 | `2ef6580bfd5b4c45018c2e4003751826f65cdcf9` | 0 / 163 | 基准祖先 | 无 branch-only delta | `f1-d@2ef6580bfd5b4c45018c2e4003751826f65cdcf9:docs/parity/F1-D.md:1` |
| `f2-c` | `132a95d88606defa79421d15523427a592bd0053` | 2026-10-12T01:45:37+08:00 | `5450a35af461af5743afff283e9ba4b6be162492` | 1 / 153 | 分叉 | backend-adapter/src, core/atlas, docs/parity, frontend/src | `f2-c@132a95d88606defa79421d15523427a592bd0053:backend-adapter/src/client.ts:137` |
| `f2-d` | `96520ce0a3f78733dab4be53939d1b8e3ecb8cad` | 2026-10-12T01:45:37+08:00 | `5450a35af461af5743afff283e9ba4b6be162492` | 1 / 153 | 分叉 | docs/parity | `f2-d@96520ce0a3f78733dab4be53939d1b8e3ecb8cad:docs/parity/F1-D.md:1` |
| `feat/personal-todos` | `f1b20f6eca3f91f514b4fb6c48aa82c183bf0339` | 2026-10-15T12:50:21+08:00 | `66d26367b4c6040d7fdd5f51fdd9e3a9f2b2458f` | 1 / 54 | 分叉 | .gitignore, core/atlas, frontend/src | `feat/personal-todos@f1b20f6eca3f91f514b4fb6c48aa82c183bf0339:.gitignore:28` |
| `fix/core-papercuts` | `01ecfe1e23f46a30854cdc71101a63ab554731b0` | 2026-10-14T13:04:20+08:00 | `01ecfe1e23f46a30854cdc71101a63ab554731b0` | 0 / 60 | 基准祖先 | 无 branch-only delta | `fix/core-papercuts@01ecfe1e23f46a30854cdc71101a63ab554731b0:core/tests/test_kernel_tool_error_regressions.py:1` |
| `fix-p1-audit` | `56615d0f21b39c4cf30a6d14972e65174461c32c` | 2026-10-15T23:42:43+08:00 | `fd5efb1afbdad253ed27e0f96ae35e991c179e4a` | 7 / 20 | 分叉 | config, core/atlas, frontend, frontend/scripts, frontend/src, package-lock.json | `fix-p1-audit@56615d0f21b39c4cf30a6d14972e65174461c32c:config/atlas.example.toml:41` |
| `frontend-parity` | `02fb0f032938c0a32a5c38f30ad51768f2123713` | 2026-09-30T08:43:29+08:00 | `02fb0f032938c0a32a5c38f30ad51768f2123713` | 0 / 714 | 基准祖先 | 无 branch-only delta | `frontend-parity@02fb0f032938c0a32a5c38f30ad51768f2123713:docs/PARITY.md:1` |
| `h1-core-hardening` | `2db55ac263fcb24ef23f679cbcea089b6140b9e7` | 2026-10-05T19:43:15+08:00 | `2db55ac263fcb24ef23f679cbcea089b6140b9e7` | 0 / 378 | 基准祖先 | 无 branch-only delta | `h1-core-hardening@2db55ac263fcb24ef23f679cbcea089b6140b9e7:tasks/CURRENT.md:1` |
| `main` | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | 2026-10-06T06:18:06+08:00 | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | 0 / 340 | 基准祖先 | 无 branch-only delta | `main@aa6196f550098cc46081dc6db2c376cb87ddffa5:core/pyproject.toml:1` |
| `mem-acceptance` | `07ca0fa8a53b08bf30f7d6edffab9a5824cfe56a` | 2026-10-16T15:56:49+08:00 | `ec6ac93673f29358ed40962aeb446c07b7cb6acc` | 4 / 5 | 分叉 | docs/memory | `mem-acceptance@07ca0fa8a53b08bf30f7d6edffab9a5824cfe56a:docs/memory/build/ACCEPTANCE.md:1` |
| `mem-integrate` | `4046764fbabda187a4b329c830a4b9cab9631951` | 2026-10-16T18:13:12+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 46 / 14 | 分叉 | .gitignore, core, core/atlas, core/tests, docs/memory, scripts | `mem-integrate@4046764fbabda187a4b329c830a4b9cab9631951:.gitignore:8` |
| `mem-m1` | `11b6eddf7f55fb3ef3f56bb2f032ec46d298c5cb` | 2026-10-16T14:58:29+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 7 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m1@11b6eddf7f55fb3ef3f56bb2f032ec46d298c5cb:core/atlas/agent/run_phases.py:35` |
| `mem-m2` | `5ffb1a16e7bdf73733198beefe8d2f581e04a3b0` | 2026-10-16T14:29:51+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 5 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m2@5ffb1a16e7bdf73733198beefe8d2f581e04a3b0:core/atlas/agent/run_phases.py:476` |
| `mem-m3` | `211962cd8dd0a459c730a9b5ee4a73e34dbf44b6` | 2026-10-16T14:52:57+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 8 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m3@211962cd8dd0a459c730a9b5ee4a73e34dbf44b6:core/atlas/agent/run_phases.py:476` |
| `mem-m4` | `a0acc44de98a4df72239e267f823d3697b2d21c2` | 2026-10-16T15:01:01+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 13 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m4@a0acc44de98a4df72239e267f823d3697b2d21c2:core/atlas/agent/run_phases.py:476` |
| `mem-m5` | `720de7110f6f1e2db733b709575f5150c64fb0ad` | 2026-10-16T15:04:01+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 9 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m5@720de7110f6f1e2db733b709575f5150c64fb0ad:core/atlas/agent/run_phases.py:476` |
| `mem-m6` | `b8eec99ec5a60c9292764dc4e5ba15c20e4e0d29` | 2026-10-16T15:04:31+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 15 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m6@b8eec99ec5a60c9292764dc4e5ba15c20e4e0d29:core/atlas/agent/delegation_memory.py:1` |
| `mem-m7` | `ba38782b871aff468737ef5d54387de462b79597` | 2026-10-16T14:42:53+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 6 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m7@ba38782b871aff468737ef5d54387de462b79597:core/atlas/agent/run_phases.py:476` |
| `mem-m8` | `0cc5fff4ecf4ecbc3fa4e95b118da990579e09c7` | 2026-10-16T15:13:02+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 15 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m8@0cc5fff4ecf4ecbc3fa4e95b118da990579e09c7:core/atlas/agent/run_phases.py:476` |
| `mem-m9` | `65a7776370691d37d65f026af4d08efe1c8e19f5` | 2026-10-16T14:29:17+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 6 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `mem-m9@65a7776370691d37d65f026af4d08efe1c8e19f5:core/atlas/agent/run_phases.py:476` |
| `memory-purge` | `7826e91c6c71dfc180f6fad6136b5eb53a9dab52` | 2026-10-15T00:20:44+08:00 | `7826e91c6c71dfc180f6fad6136b5eb53a9dab52` | 0 / 46 | 基准祖先 | 无 branch-only delta | `memory-purge@7826e91c6c71dfc180f6fad6136b5eb53a9dab52:docs/memory/PURGE-RESULT.md:1` |
| `memory-survey` | `57712d33652f8d14af372cca062dec8b1d21ad4b` | 2026-10-16T14:20:49+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 14 / 14 | 分叉 | docs/memory | `memory-survey@57712d33652f8d14af372cca062dec8b1d21ad4b:docs/memory/CLAUDE-REVIEW-V2.md:1` |
| `memory-survey-a` | `a029ca6abfabf51f7d6bf6469358d23b3f879e8b` | 2026-10-16T13:44:02+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 3 / 14 | 分叉 | docs/memory | `memory-survey-a@a029ca6abfabf51f7d6bf6469358d23b3f879e8b:docs/memory/CLAUDE-REVIEW-V2.md:1` |
| `memory-survey-b` | `af1971c8a3878dba08683c75c5750d0018d697e2` | 2026-10-16T13:46:06+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 2 / 14 | 分叉 | docs/memory | `memory-survey-b@af1971c8a3878dba08683c75c5750d0018d697e2:docs/memory/CLAUDE-REVIEW-V2.md:1` |
| `memory-survey-c` | `f92b8998d6b91b135861600bf7b1415e0e20b445` | 2026-10-16T13:52:14+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 4 / 14 | 分叉 | docs/memory | `memory-survey-c@f92b8998d6b91b135861600bf7b1415e0e20b445:docs/memory/CLAUDE-REVIEW-V2.md:1` |
| `memory-v1` | `9ace88c5731ed8be6dd7406d758161236938e2de` | 2026-10-15T23:59:02+08:00 | `c8a78db8da93a25623e4faa30c067e61d32c846d` | 5 / 23 | 分叉 | core/atlas, core/tests, docs/memory, frontend/src | `memory-v1@9ace88c5731ed8be6dd7406d758161236938e2de:core/atlas/agent/run_phases.py:216` |
| `memory-w0` | `3a5e41c5c47767361d979deb2f00b09cbf1866ff` | 2026-10-15T02:50:26+08:00 | `3a5e41c5c47767361d979deb2f00b09cbf1866ff` | 0 / 40 | 基准祖先 | 无 branch-only delta | `memory-w0@3a5e41c5c47767361d979deb2f00b09cbf1866ff:docs/memory/W0-RESULT.md:1` |
| `memory-w1` | `9ace88c5731ed8be6dd7406d758161236938e2de` | 2026-10-15T23:59:02+08:00 | `c8a78db8da93a25623e4faa30c067e61d32c846d` | 5 / 23 | 分叉 | core/atlas, core/tests, docs/memory, frontend/src | `memory-w1@9ace88c5731ed8be6dd7406d758161236938e2de:core/atlas/agent/run_phases.py:216` |
| `memory-w2-api` | `aa14c3173392d0fc60ec3e401e4495a2d3357cb7` | 2026-10-16T01:33:06+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 2 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7:core/atlas/agent/run_phases.py:476` |
| `memory-w2-fix` | `6c5240e41381a1eda4f0c8d74687c47476f95721` | 2026-10-16T12:32:33+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 3 / 14 | 分叉 | core, core/atlas, core/tests, docs/memory | `memory-w2-fix@6c5240e41381a1eda4f0c8d74687c47476f95721:core/atlas/agent/run_phases.py:476` |
| `memory-w2-plan` | `9e70bf33abcf93301987c943eb3cd15bf2ab6530` | 2026-10-16T00:33:28+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 1 / 14 | 分叉 | docs/memory | `memory-w2-plan@9e70bf33abcf93301987c943eb3cd15bf2ab6530:docs/memory/prototype-memory-browser.html:1` |
| `memory-w2-ui` | `11153a028feace09e952e23544e0adf1d155887c` | 2026-10-16T00:52:19+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 2 / 14 | 分叉 | docs/memory, frontend/src | `memory-w2-ui@11153a028feace09e952e23544e0adf1d155887c:docs/memory/prototype-memory-browser.html:1` |
| `research/atlas-memory-2026-10-16-handoff` | `bc42b5091563d3f8ee5d25ffc3266ea1c72f6af8` | 2026-10-16T12:15:11+08:00 | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | 12 / 340 | 分叉 | docs/research | `research/atlas-memory-2026-10-16-handoff@bc42b5091563d3f8ee5d25ffc3266ea1c72f6af8:docs/research/atlas-memory/2026-10-16/README.md:1` |
| `sol/t1-prep` | `0e37af241463d4ed3a71a25de60f3dad0def97bb` | 2026-10-03T01:18:27+08:00 | `6df1addb875b1d7fb63f07eb4613429438edd68c` | 6 / 501 | 分叉 | tasks, tasks/results, tasks/reviews, tasks/taskbooks, tests/t1 | `sol/t1-prep@0e37af241463d4ed3a71a25de60f3dad0def97bb:tasks/results/ATLAS-T1-PREP.result.md:1` |
| `sol/x-prep` | `9972813e4dfcd7d5fdf99dde63400312b7cdfd3d` | 2026-10-03T05:36:22+08:00 | `6df1addb875b1d7fb63f07eb4613429438edd68c` | 4 / 501 | 分叉 | tasks, tasks/taskbooks | `sol/x-prep@9972813e4dfcd7d5fdf99dde63400312b7cdfd3d:tasks/SOL-CURRENT.md:1` |
| `sol/x-prep-wip-2026-10-05` | `447982a7fbee426d23826392174f2cdd9c8812e4` | 2026-10-05T22:00:58+08:00 | `6df1addb875b1d7fb63f07eb4613429438edd68c` | 3 / 501 | 分叉 | docs/research, tasks, tasks/taskbooks | `sol/x-prep-wip-2026-10-05@447982a7fbee426d23826392174f2cdd9c8812e4:docs/research/2026-10-03-x-prep/00-summary.md:1` |
| `task/luna-audit-model-policy-20261017` | `1557f612604a634ebad28728c2787a8085cfa946` | 2026-10-17T14:46:15+08:00 | `0b1ba4114e25643369c95bfac85d37563788444f` | 1 / 0 | 后继 | tasks/taskbooks | `task/luna-audit-model-policy-20261017@1557f612604a634ebad28728c2787a8085cfa946:tasks/taskbooks/ATLAS-LUNA-GLOBAL-AUDIT-MODEL-RETRY-20261017.md:1` |
| `track-upstream` | `aef275ed649f49bd3396f4ffca65cb1a1a7d4c48` | 2026-10-12T13:11:14+08:00 | `aef275ed649f49bd3396f4ffca65cb1a1a7d4c48` | 0 / 90 | 基准祖先 | 无 branch-only delta | `track-upstream@aef275ed649f49bd3396f4ffca65cb1a1a7d4c48:core/atlas/api/workspace_router.py:1` |
| `ui/reasoning-zcode` | `5e2ec97c55a530d9c944d184a070ed60417d00c6` | 2026-10-14T13:31:02+08:00 | `5e2ec97c55a530d9c944d184a070ed60417d00c6` | 0 / 57 | 基准祖先 | 无 branch-only delta | `ui/reasoning-zcode@5e2ec97c55a530d9c944d184a070ed60417d00c6:frontend/src/renderer/App.tsx:1` |
| `ui/streamdown` | `66d26367b4c6040d7fdd5f51fdd9e3a9f2b2458f` | 2026-10-14T17:48:33+08:00 | `66d26367b4c6040d7fdd5f51fdd9e3a9f2b2458f` | 0 / 54 | 基准祖先 | 无 branch-only delta | `ui/streamdown@66d26367b4c6040d7fdd5f51fdd9e3a9f2b2458f:frontend/src/renderer/components/ConversationMessage.tsx:1` |
| `ui-redesign` | `0b1ba4114e25643369c95bfac85d37563788444f` | 2026-10-16T19:23:17+08:00 | `0b1ba4114e25643369c95bfac85d37563788444f` | 0 / 0 | 基准祖先 | 无 branch-only delta | `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f:core/atlas/kernel/loop.py:1` |
| `unified-memory/waves` | `931ef643126dc79a6e7fa820517d0253e07128cc` | 2026-10-07T19:50:41+08:00 | `931ef643126dc79a6e7fa820517d0253e07128cc` | 0 / 310 | 基准祖先 | 无 branch-only delta | `unified-memory/waves@931ef643126dc79a6e7fa820517d0253e07128cc:core/tests/unified_memory/test_repair_baseline.py:1` |
| `websearch` | `1581b4f84ca7dd9f3ef0b35eff0127026f9b2bde` | 2026-10-15T18:34:06+08:00 | `1581b4f84ca7dd9f3ef0b35eff0127026f9b2bde` | 0 / 19 | 基准祖先 | 无 branch-only delta | `websearch@1581b4f84ca7dd9f3ef0b35eff0127026f9b2bde:config/atlas.example.toml:1` |
| `wip/c3-frontend-from-laptop` | `a451723b38be3e01b886811f16e6f0cca8d0ef33` | 2026-10-02T07:10:40+08:00 | `08c1a581a548ed9a52f188e7e74bf044a8f8c0b2` | 1 / 584 | 分叉 | backend-adapter/src, core/atlas, core/tests, frontend/src | `wip/c3-frontend-from-laptop@a451723b38be3e01b886811f16e6f0cca8d0ef33:backend-adapter/src/client.ts:2` |
| `wip/f4-bc-20261009` | `bfea9fbfa69df15a5240d721be60c6a9d100e867` | 2026-10-10T00:10:14+08:00 | `1c13826f9f05c04e5a7564ae18c89a82091fc727` | 2 / 265 | 分叉 | core/atlas, core/tests, docs/plan, scripts/memory_v1 | `wip/f4-bc-20261009@bfea9fbfa69df15a5240d721be60c6a9d100e867:core/atlas/agent/run_phases.py:35` |
| `wip/host-uncommitted-2026-10-04` | `a2c200c8f4668a0bf24800cc09add7d0e99766fd` | 2026-10-04T19:05:39+08:00 | `a2c200c8f4668a0bf24800cc09add7d0e99766fd` | 0 / 432 | 基准祖先 | 无 branch-only delta | `wip/host-uncommitted-2026-10-04@a2c200c8f4668a0bf24800cc09add7d0e99766fd:arx.html:1` |
| `wip/kernel-deep-research-20261015` | `7f0ee93293786f8d884cdf45650f1fb8aa7e29c4` | 2026-10-16T16:11:49+08:00 | `0e989795622538dfaa300db76c792d1710b71d75` | 1 / 14 | 分叉 | core/atlas | `wip/kernel-deep-research-20261015@7f0ee93293786f8d884cdf45650f1fb8aa7e29c4:core/atlas/kernel/loop.py:81` |
| `zcode/c5-models-parallel` | `4b3083430d659f8aa71db5defa9bc6c802a948b6` | 2026-10-02T19:03:17+08:00 | `4b3083430d659f8aa71db5defa9bc6c802a948b6` | 0 / 546 | 基准祖先 | 无 branch-only delta | `zcode/c5-models-parallel@4b3083430d659f8aa71db5defa9bc6c802a948b6:tasks/ZCODE-CURRENT.md:1` |
| `zcode/c6a-lsp-parallel` | `fe3ecd498e5361163ee864cc70ce04b8cdb66ecd` | 2026-10-02T21:46:20+08:00 | `fe3ecd498e5361163ee864cc70ce04b8cdb66ecd` | 0 / 531 | 基准祖先 | 无 branch-only delta | `zcode/c6a-lsp-parallel@fe3ecd498e5361163ee864cc70ce04b8cdb66ecd:tasks/ZCODE-CURRENT.md:1` |

## `ui-redesign` 与 `absorb-all`

两者 merge-base 为 `6bb3e10c6263e796783c11297344a7b64544a122`。相对该点，ui-redesign 基准独有 17 个提交 / 39 个路径（W1/W2 原生记忆库及 UI 等）；absorb-all 独有 20 个提交 / 46 个路径（session 子会话与 discovery/evolution 等）。这不是整分支合并建议。

absorb-all 主要独有代码：`core/atlas/sessions/hub.py:74,192`（hub / create-and-start）、`core/atlas/sessions/store.py`、`core/atlas/sessions/tools.py`；FastAPI router 在 `core/atlas/api/sessions_router.py:14,23,49,70-92`，注册在 `core/atlas/api/application.py:52,134`。Discovery 实现在 `core/atlas/evolution/discovery/service.py`、`judge.py`、`sources.py`，UI 入口 `frontend/src/renderer/components/evolution/DiscoveryPanel.tsx:16`；子会话 UI `frontend/src/renderer/components/sessions/LinkedSessions.tsx:12`。上述均以 `absorb-all@8d7b01d829f1332e9305fe8ee56758a6294139f7` 为证据。

两支共同修改 4 个 UI/runtime 文件：`frontend/src/renderer/components/MessageThread.tsx`（基准 hunk 196；absorb hunk 44）、`frontend/src/renderer/components/timeline.ts`（基准新增 hunk 391；absorb hunk 96）、`frontend/src/renderer/services/runtimeEvents.ts`（基准 hunk 27；absorb新增 hunk 34）、`frontend/src/types/runtime.ts`（基准 hunk 7；absorb新增 hunk 20）。静态 `git merge-tree <merge-base> <ui-redesign> <absorb-all>` 未报告冲突标记，四路径都可自动合并；这些交叠区仍需语义核对事件类型/时间线排序与消息展示。分支特定 hunk：基准 `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`；另一侧 `absorb-all@8d7b01d829f1332e9305fe8ee56758a6294139f7`。

建议把 sessions 与 discovery 作为分开的集成候选，先核 API/agent tool/事件/Electron/UI 的完整接线和生命周期，再分别集成；忽略吸收分支上的自动发现草稿 taskbooks（6 个）作为代码候选。不要直接 merge 46-path 分支。

## 可施工候选（按谱系，实际可用性由对应 W 核验）

| 分支 | 有效独有贡献 / 证据 | 建议 |
|---|---|---|
| `absorb-all` | sessions hub/API/tools + linked sessions UI；evolution discovery API/UI。完整来源 SHA/路径见上。 | 拆为 sessions 与 discovery 两个审查项；核生命周期和真实入口后再评估。 |
| `fix-p1-audit` `56615d0f21b39c4cf30a6d14972e65174461c32c` | 7 个提交：A01 stream retry/status (`3f153782`)，A02 cancellable streaming (`fae0d284`)，A05 GitHub subprocess offload，A19 local Git root/path restrictions，A17 close stdin，A06 patched SQLite，A08 frontend dependency pin。 | W1 对照 A01/A02；W4/W6 逐项筛过时/已重写实现。禁止整分支 cherry-pick。 |
| `f2-c` `132a95d88606defa79421d15523427a592bd0053` | 1 个提交、26 文件：`core/atlas/api/mcp_oauth.py`、`mcp_settings_router.py`、`settings_audit_router.py`、`core/atlas/tools/mcp_client.py`，Electron configured-source update / local crash reports 和 Settings/MCP UI。 | W3/W4 核当前接线、权限/数据边界及等价实现；不可按“一提交”忽略。 |
| `f2-d` `96520ce0a3f78733dab4be53939d1b8e3ecb8cad` | merge-base=`track-upstream` `5450a35af461af5743afff283e9ba4b6be162492`；唯一分支提交只更新 `docs/parity/F1-D.md`，无前端 diff。 | 只留历史文档证据；不可把 C3 UI 归到此分支。 |
| `wip/c3-frontend-from-laptop` `a451723b38be3e01b886811f16e6f0cca8d0ef33` | 唯一提交 “older laptop session”，有 orchestration UI 草稿；branch-only frontend/backend-adapter 变化。 | W3 判定孤岛/接线，不以草稿当功能已交付。 |
| `feat/personal-todos` `f1b20f6eca3f91f514b4fb6c48aa82c183bf0339` | 1 个 `floating personal to-do panel` 提交；source changes 在 core/frontend。 | W3 核 UI 入口和数据持久性；避免与 C3 TeamBoard 概念误并。 |
| `mem-integrate`, `mem-m1..m9`, `memory-survey*`, `memory-w2-*`, `memory-v1/w1` | 多分支 share merge-base `0e989795622538dfaa300db76c792d1710b71d75`；完整独有 paths 见 JSON；W5 当前检视确认部分功能仍被删改，`mem-integrate` 相对当前 memory diff 16 files、530 insertions / 2584 deletions；缺 `source_ref.py` exact message UID、`lifecycle.py` per-source checkpoint、`recall.py` layered recall、`claim_resolution.py`。 | 不能以当前有 memory library 就判全部吸收；按 M1–M9 语义做逐文件迁移矩阵，不合并旧分支整体。 |
| `wip/kernel-deep-research-20261015` `7f0ee93293786f8d884cdf45650f1fb8aa7e29c4` | 1 unique commit; `core/atlas/kernel/loop.py` branch delta，research notes associate run behavior. | W2/W5 检视静态风险与 current code 差异。 |
| `ctx-opt` `bddafde3ce6f76fb953085b89c096b68188e1ea0` | 1 unique `feat(context): optimize compaction and handoff` commit; source delta spans context/handoff. | W2 按当前 compaction/handoff 实际入口核对；只移植仍未等价行为。 |
| `card-b-tc-10` / `card-c-tc-04` | 各2提交：B-TC-10 trajectory/background debugging（`d10d9dca`），C-TC-04 extension host capabilities（`8046c93d`），含parity结果。 | W7/W4 对照现状入口，不以 parity 文档代替代码/实测。 |
| `wip/f4-bc-20261009`, `sol/x-prep-wip-2026-10-05`, `sol/t1-prep` | 分叉但多为旧 WIP/checkpoint、研究与 taskbook；W4 报告 f4 仅 tool_node/run_phases 测试时钟/记忆捕获差异，sol/x prep 是2026-10-03研究/taskbook，无工具实现。 | 按 worker 发现的当前差异保留历史；不作为整分支集成。 |

### 本机本地但未在 GitHub 的 branch refs

8 个基线 local-only refs 完整数据在 [`LOCAL-REFS.json`](evidence/LOCAL-REFS.json)。相对指定基准 2 个 ref 有 branch-only commits：

- `codex/desktop-repair-20261013` `b177a6a94a7f1a9adb2891955a37cd4d4490054d`：3 个提交（`67f5d317`, `66247515`, `b177a6a9`），改动 memory authority/cleanup/runtime 与 Electron staging/packaging，存在 checkout `D:/atlas-desktop-repair-20261013`。属于可选择性复核的本地未推送差异，不能整支回放。
- `p11b-worker-leftover` `9379d6b499a8d1dd316ff7f8af274cf5285a8654`：1 ahead commit `feat(autonomous): operational observability for goal execution (P11B)`，tip commit 对父提交无 tree/path diff（empty commit），没有可集成代码。
- 另外 6 个 refs 对基准为 ahead=0。W1 与 root 的 review refs 是本轮任务期间新建/可变分支，已从该起始 local-ref 快照排除，避免把运行中 worker refs 伪装成起始状态。详细 SHA、tree、merge-base、ahead/behind 与工作树位置见 JSON。

## Worktree 状态（仅元数据与源码路径）

本次只查询 `core/atlas`、`frontend`、`engine` 路径的 tracked/untracked 状态；排除了 `data/upstream/staging` worktree 和所有真实 data 内容。发现 6 个 checkout 有源码路径变更：

- `D:/Atlas` `ui-redesign`：dirty；多个 agent/kernel/tool 文件、`engine/config.yaml`、timeline 与新的 expert_harness/research 源码。文件清单仅作状态证据，未读未改。
- `D:/atlas-boot-core`：dirty engine_core 配置/代理/期限源文件。
- `D:/atlas-boot-int`：dirty `engine/config.yaml`。
- `D:/atlas-f1-d`：dirty tools/runtime 文件与新 workspace move-state。
- `D:/atlas-luna-w1-20261017`：模型策略 worker 的源文件变更。
- `D:/atlas-p1fix-verify2`：dirty frontend preload test script。

除此以外，在查询的三个源码目录范围内没有发现 dirty entries。未读凭据/真实 data，也未检查根目录非源码 untracked 内容。实际运行进程/运行源码基线由主执行者负责，本 W0 branch doc 不从进程推断运行版本。

## 证据与覆盖边界

- 每个远程分支的 branch + 完整 tip SHA + path:line 都在上表，机器表另含完整 unique paths；同树分支已标注去重。
- merge-base/ahead/behind 均在同一个 baseline SHA 下计算；用于结论的远程 refs 为 GitHub 全量 74/74 且与 local `origin/*` tip 匹配。
- 分支历史本身不证明功能当前存在；absorbed 是提交祖先关系而非需求验收。各 W2–W7 需结合当前源码入口继续复核。





