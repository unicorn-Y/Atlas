# W14 结果：前端输入与附件（D5、D6）

日期：2026-11-14  
分支：`zcode/dsh-w14`

## 状态

- **D5 — PARTIAL。** 文件、图片、白板图、最近截图现在先按 SHA-256 内容寻址写入 IndexedDB，成功后才进入 Composer；展示暂存进度并可取消。每会话草稿保存暂存引用，切换/重载后可从 IndexedDB 恢复。发送仍把 base64 内联到 `run.start`，没有有效的 UI 重载或传输端到端验收，因此未关闭。
- **D6 — PARTIAL。** 草稿按会话序列化文本、mention chip 和暂存附件引用；提交时将各类 chip 序列化进模型文本。单测验证序列化及会话隔离。真实 UI 重载和真实模型回合均未通过验证，因此未关闭。

## 改动文件

- `frontend/src/renderer/services/attachmentStaging.ts` — SHA-256 内容寻址、IndexedDB 写入/恢复、可中止读取和进度回报。
- `frontend/src/renderer/services/attachmentStaging.test.ts` — 内容寻址、进度和取消单测。
- `frontend/src/renderer/services/composerDraft.ts` — 按会话保存/读取结构化草稿，并把 chip 序列化到模型文本。
- `frontend/src/renderer/services/composerDraft.test.ts` — 草稿 round-trip、会话隔离和 chip 序列化单测。
- `frontend/src/renderer/App.tsx` — 接入附件暂存、草稿恢复、取消按钮和提交序列化。
- `frontend/src/renderer/components/Composer.tsx` — 附件暂存进度区提供取消操作。
- `docs/parity/DSH-GAP-LEDGER.md` — D5/D6 更新为 PARTIAL 并记录剩余差距。

## 验证输出

定向测试：

```text
npm test -- src/renderer/services/composerDraft.test.ts src/renderer/services/attachmentStaging.test.ts src/renderer/components/Composer.test.ts
Test Files  3 passed (3)
Tests       11 passed (11)
exit code   0
```

生产构建：

```text
npm run build
✓ 5437 modules transformed.
✓ built in 20.67s
exit code 0
```

构建有既有的 `ExpertModePanel` 动态/静态导入提示和大 chunk 提示；没有 TypeScript 或构建错误。

全量 frontend 测试：

```text
npm test
Test Files  4 failed | 50 passed (54)
Tests       12 failed | 249 passed (261)
Errors      8 errors
exit code   1
```

失败涉及 renderer 的 X2、store 对话历史/分页测试，以及 Electron navigation/backendProcess 启动测试；另有 8765 被 PID 26980 占用的异步拒绝输出。此批没有修改这些模块。W14 定向测试在全量运行中通过。

`git diff --check`：exit code 0。

## 真实模型尝试（8834）

按 runner 执行：

```text
python scripts/dsh_live_ws_check.py 8834 "Reply with exactly the word: OK"
[event] run.started
[terminal] run.failed data={"category":"runtime","detail":"TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"}
[reply] ''
[result] terminal=run.failed chars=0
exit code 1
```

run log `56dc0b20-212a-42cf-a283-f490a3a7bb16` 记录输入/输出 token 均为 0；模型未返回 `OK`。这是运行时阻塞，不作为 D5/D6 的成功证据。8834 上由本批启动的 uvicorn 进程随后已停止。
