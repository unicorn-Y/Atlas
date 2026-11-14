# WAVE 3 — X6 结果（桌面端）

日期：2026-11-14  
分支：`wave3`  
基线：`2bc3a626`  
提交：本批提交后补录

## 逐条结论

| Row | 状态 | 依据 / 未完成项 |
|---|---|---|
| D3 | PARTIAL | 高频 delta 已折叠进 per-node state，非投影状态事件不重建；结构事件仍重投影，重连未压缩回放。 |
| D4 | CLOSED | `registerConversationNode` 按 kind 注册 renderer 并返回 disposer；组件测试覆盖 builtin/extension 渲染与卸载；定向 Vitest 通过，renderer/Electron TS 检查均 0 错误。 |
| D5 | PARTIAL | IndexedDB SHA-256 staging、进度/取消和发送前暂存已存在；内联 base64 仍用作 run.start 负载，缺 UI reload 和端到端证据。 |
| D6 | PARTIAL | composer draft 按 session 保存文本、mention、附件引用；缺真实 UI reload 与模型行为验证。 |
| D8 | PARTIAL | Inspector 仍是固定单列 tab union；无 split tree、浮动面板或 per-session layout 持久化。 |
| D10 | PARTIAL | 自动检查、抖动退避和本地 journal 已接入；强制版本策略缺失。 |
| D11 | PARTIAL | hunk 级接受/拒绝和行评论比目标动作更强；缺并排/换行 diff 与 hover 预览。 |
| D12 | PARTIAL | checkpoint manifest 有变更文件数据；前端只显示一行脚注，缺目标级 workspace/changes 展示。 |
| D15 | PARTIAL | 审批卡选项较丰富，但卡片在滚动内容中可被滚走。 |
| D16 | PRESENT-PARITY | Markdown/图片/PDF/xlsx/pptx/HTML 预览存在；本批未改 renderer，也未将其标 CLOSED。 |
| D17 | PARTIAL | namespace i18n API 与 updates namespace 已接入；全局 locale 目录和 MutationObserver 替换尚未迁移。 |
| D18 | PARTIAL | 有三套主题与自定义颜色；半径 token 标准、token-only 颜色 spec 未覆盖全组件。 |
| D19 | PARTIAL | 有全局 focus-visible 与手写 aria；缺框架级 focus/IME/reduced-motion contract。 |
| D20 | PRESENT-PARITY | Electron 单实例和 deep link 路径存在；本批不改实现。 |
| D21 | PRESENT-STRONGER | 托盘包含 backend stage/component/safe-mode 状态，强于目标；本批不改实现。 |
| D22 | PRESENT-PARITY | 原生菜单、快捷键和 Keymap 接线存在；本批不改实现。 |
| D23 | PARTIAL | 脱敏崩溃报告和安全模式存在；禁用全部插件后重启的完整流程未证明。 |
| D24 | PRESENT-STRONGER | fork/fork+summary 分支能力已存在；本批不改实现。 |
| D25 | PRESENT-STRONGER | 三模式 rewind、preview、redo 与文件还原存在；按计划只保留更强实现，不改实现。 |
| D26 | PRESENT-PARITY | Plan review 与 UltraplanPanel 存在；本批不改实现。 |
| D27 | PRESENT-PARITY | queue/steer/redirect panel 与 store 操作存在；本批不改实现。 |
| D28 | PRESENT-STRONGER | 语音输入、TTS 与通话浮层覆盖更宽；本批不改实现。 |
| D29 | PARTIAL | 更早历史使用 id 游标和满页启发式；未证明目标加载协议/边界语义。 |
| D30 | PARTIAL | rollout 中有 trajectory 与原始事件切换；缺完整 Chat/Trajectory 双模式 renderer。 |
| D31 | PRESENT-STRONGER | PaneWorkspace 有递归 split tree 和多窗口能力；按计划只加回归、不改实现。 |
| D32 | PRESENT-STRONGER | 消息操作有编辑重发、fork、fork+摘要、rewind、copy；按计划只加回归、不改实现。 |
| D33 | PARTIAL | slash command 服务支持去重与模糊排序；命令来源仍由 App.tsx 静态数组提供。 |

## 验证命令与实际输出

全 frontend Vitest：

```powershell
cd D:\Atlas\frontend
npm test -- --reporter=dot
```

```text
Test Files  4 failed | 59 passed (63)
Tests       8 failed | 277 passed (285)
Errors      2 errors
Duration    5.00s
npm error code 1
```

失败包括前端已存在的多项 store/Electron/navigation/UI 用例；输出中另外出现两个 `src/main/electron.navigation.test.ts` 未处理 rejection：

```text
TypeError: dialog.showErrorBox is not a function
```

该整套失败不掩盖 D4 的定向 component 结果，也不作为其他 D 行通过证据。

D4 component test：

```powershell
npx vitest run --root . src/renderer/components/ConversationNodeRegistry.test.tsx
```

```text
Test Files  1 passed (1)
Tests       2 passed (2)
Duration    1.52s
```

Renderer TypeScript：

```powershell
npx tsc -p tsconfig.renderer.json --noEmit
```

```text
npm notice run tsc -p tsconfig.renderer.json --noEmit
exit code: 0
```

Electron TypeScript：

```powershell
npx tsc -p tsconfig.electron.json --noEmit
```

```text
npm notice run tsc -p tsconfig.electron.json --noEmit
exit code: 0
```

## 本批变更与边界

- `frontend/src/renderer/components/ConversationActivity.tsx` 与 `ConversationNodeRegistry.test.tsx` 在基线已有 keyed renderer registry 与 component test；本批复核并将 D4 从 ABSENT 更正为 CLOSED，没有新增源码。
- `docs/parity/DSH-GAP-LEDGER.md`：记录 D4 的三类验收证据。
- `tasks/dsh-parity/waves/RESULT3-X6.md`：逐行状态与命令输出。
- D25/D31/D32 保留 PRESENT-STRONGER 实现，没有为“按计划只加回归”重复加测试或改代码；账本已有这些能力的广泛回归覆盖。
- 未运行真实模型；D 区验收不要求真实模型。除 D4 外，本批没有 D 行满足全部行为要求并闭环，因此没有把其余行标为 CLOSED。
