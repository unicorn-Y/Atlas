# ATLAS-C2-TOOLS-CONTEXT 独立验收

日期：2026-10-02  
结论：**通过，可以进入 C3。**

## 验收依据

核对：
- Atlas 代码提交 `5970f176b8bae85f6cb46a53bccb0a03aee6cab5`
- Atlas 结果提交 `83f19b064f0896166c576389c166d8b6341f19e1`
- Hermes fork 提交 `e287231d7906bcce5bc373d20fb2e3e1e6427220`
- `docs/plan/CORE-PARITY.md` 的 C2 行
- C2 聚焦测试、WebSocket E2E 和前端检查结果

## 结论核对

C2 目标均已落地：

- **legacy LangGraph**：旧图循环、engine 切换、只服务 legacy 的测试和依赖已删除；Hermes 仍复用的 Atlas 工具、checkpoint、权限和生命周期适配保留。
- **L3 防打转**：同 run / 同文件编辑计数，第 6 次起仅提醒，不阻断、不自动回滚。
- **T3 图片读取**：复用 Hermes 图片预处理；视觉模型直读，配置视觉模型时走 `vision_analyze`，否则明确提示；前端保留图片 envelope 并显示缩略图。
- **T5 编辑容错**：只从 OpenCode 搬入 Hermes 原来没有的唯一锚点可变长度匹配；歧义仍拒绝；来源和 MIT notice 已登记。
- **X5 模型族提示**：Claude、GPT/Codex、Gemini、DeepSeek、Kimi、GLM、Qwen、MiniMax、默认均有短稳定指引，没有复制第二套大 system prompt。
- **X1 压缩摘要**：保留 Hermes ContextCompressor，只补固定的下一步/交接结构。
- **X10 新上下文**：只替换下一次模型 live context，Atlas 历史仍保留，没有新建第二套会话库。
- **Windows shell**：生产逻辑为 `auto`，Windows 优先 Git Bash、忽略 WSL/WindowsApps/system32 的 bash，找不到再 PowerShell；显式 shell 仍尊重用户选择。

Hermes fork 的改动集中在 ContextCompressor、tool round handoff、tool guardrails/fuzzy match 和对应测试，属于 C2 必需修改，没有扩成第二套框架。

## 测试判断

施工按任务书只跑一次后端全量：
`1030 passed, 9 skipped, 1 failed`。

唯一失败是旧测试仍把无显式 shell 的 terminal 翻译写死为 PowerShell。生产实现已经改成 `shell="auto"`，随后该断言更新为当前契约并单独重跑通过。**不要求为了把汇总数字改成 0 再跑一次全量。**

其余验证：
- Hermes 聚焦：360 passed
- Atlas C2 WebSocket E2E：1 passed
- Atlas 最终聚焦组：27 passed
- 前端 renderer/electron TypeScript：通过
- Vitest：9 files / 40 tests passed
- Vite build：通过

结果文件提到全量排除了 `tests/test_computer_use.py`；C2 未改 Computer Use，且该组属于真实桌面环境专项，因此本轮不作为 C2 阻塞项。后续 Computer Use 阶段再做真实设备验收。

## 验收结论

没有发现 C2 新增的真实生产回归；也没有为了旧测试契约回退正确行为。

**ATLAS-C2-TOOLS-CONTEXT：PASS。进入 ATLAS-C3-SESSION-INTERACTION。**
