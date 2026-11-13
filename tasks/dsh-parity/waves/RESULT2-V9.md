# WAVE 2 V9 结果：D4 / D5 / D6

日期：2026-11-14

分支：`zcode/dsh2-V9`

起始 HEAD：`fa578c482d08b270b6b1b7a2bc3276108a42f956`

## Row 状态

| Row | 本轮结果 | 证据 / 未完成项 |
|---|---|---|
| D4 | PARTIAL | keyed registry 已有全部内置 kind 注册及扩展注册/disposer。registry 组件测试验证内置渲染、扩展渲染和卸载。定向测试通过；全量 Vitest 未通过，因此没有达到 WAVE2 P3 CLOSED 门槛。 |
| D5 | PARTIAL | IndexedDB 内容寻址暂存和恢复路径已有实现。本轮补了写入后恢复附件字节的 IndexedDB mock 测试，以及可取消暂存进度/失败重试的组件测试。定向测试通过；全量 Vitest 未通过，因此没有达到 CLOSED 门槛。 |
| D6 | PARTIAL | 会话草稿保存文本、mention、暂存附件引用；chip 序列化进模型文本。本轮补了模拟 renderer reload 后恢复 mention chip 的组件测试。定向测试通过；全量 Vitest 未通过，因此没有达到 CLOSED 门槛。 |

P3 前端行不要求真实模型回合；本批未启动 Atlas 后端或使用模型通道。

## 修改文件

- `frontend/src/renderer/components/Composer.tsx` — 抽出复用的附件进度/重试状态组件和草稿 mention chip 组件，原 UI 使用这些组件。
- `frontend/src/renderer/components/ComposerAttachmentStatus.test.tsx` — 验证暂存进度、取消与失败重试 UI。
- `frontend/src/renderer/components/ComposerDraftRestore.test.tsx` — 模拟 renderer 重载后读取会话草稿并渲染 mention chip。
- `frontend/src/renderer/services/attachmentStaging.test.ts` — 增加 IndexedDB mock 写入和附件字节恢复测试。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 D4–D6 实现描述和证据状态。

## 验证

定向前端测试：

```text
npm test -- --run src/renderer/components/ConversationNodeRegistry.test.tsx src/renderer/components/ComposerAttachmentStatus.test.tsx src/renderer/components/ComposerDraftRestore.test.tsx src/renderer/services/attachmentStaging.test.ts src/renderer/services/composerDraft.test.ts src/renderer/components/Composer.test.ts
Test Files  6 passed (6)
Tests       17 passed (17)
exit code   0
```

生产构建：

```text
npm run build
tsc -p tsconfig.electron.json                     exit 0
npm run build:preload                              exit 0
tsc -p tsconfig.renderer.json --noEmit            exit 0
vite build                                         exit 0
✓ 5442 modules transformed.
✓ built in 26.41s
```

构建输出包含既有 ExpertModePanel 动态/静态导入提示及大 chunk 提示。

全量 Vitest：

```text
Test Files  4 failed | 57 passed (61)
Tests       12 failed | 264 passed (276)
Errors      8
exit code   1
```

失败分布：`src/renderer/components/x2/x2.test.tsx` 2 项、`src/renderer/store/useAtlasStore.test.ts` 2 项、`src/main/electron.navigation.test.ts` 2 项、`src/main/backendProcess.test.ts` 6 项。backendProcess 用例观察到端口 8765 被 `python.exe` PID 26980 占用，进程启动检查因此提前失败。没有停止该非本批进程。其它失败未在本批范围内继续诊断。由于计划要求全量 Vitest 通过，D4–D6 都保持 PARTIAL。

## 边界

- 本轮没有改 Atlas 后端、桌面主进程或模型配置；8839 未启动，因为 WAVE2-PLAN 对 P3 前端行明确不要求真实模型验证。
- 全量测试中的 out-of-scope 失败没有改动或掩盖。
