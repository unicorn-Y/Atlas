# F4-A — 本地时区修复进度

**状态：F4-A 实现与 Atlas 验证已完成，等待总控统一验收；未提交、未推送。** Atlas 时区配置、提醒解析、IntentBridge 时区传递、Observer/Reflector/Recall 接线及真实端到端 Automation 冒烟均已有证据。总控报告 Atlas 全集 344 passed / 2 skipped；MemoryOS 专项仍由总控统一复跑验收。本文件不是整个 MEMORY-V1 阶段通过声明。

## Atlas 实现

- `user.timezone` 优先使用配置的 IANA 时区；为空时由 `tzlocal` 将 Windows 系统时区映射到 IANA，并以 `ZoneInfo` 保留 DST 规则。
- `now_utc`、`now_local`、`attach_user_timezone` 提供共享时钟/转换入口。不存在的 DST 墙钟会拒绝；重复墙钟采用第一次出现。
- `parse_due` 返回有时区的到期时间，支持本地明天、下周星期（含“下周三15点”）、今晚钟点，以及带偏移的 ISO 时间。已验证输入在 UTC 日界前后保持正确本地日期；跨 DST 的未来日期使用目标日期偏移；带说明尾文的 ISO 偏移不丢失。
- `IntentBridge` 接收同一 `AtlasConfig`，并将其传给 `create_reminder`。
- `scripts/memory_v1/f4_a_real_automation_smoke.py` 使用 Atlas `ModelRouter`，经真实 Observer 和 MemoryOS HTTP/IntentBridge 链路运行，并将全部 Atlas/MemoryOS/AutomationStore 数据限制在唯一 C 盘临时目录；证据仅记录非敏感结果。

- 最终冒烟脚本已改为真实 `MemoryObserver` → MemoryOS HTTP → `MemoryObserverDrain`/IntentBridge → AutomationStore 路径，输入自然原话“明天上午9点提醒我交报告”，用 `gemini_runtime` 的 allowlist 只提取非敏感模型/Provider metadata，并由 Atlas ModelRouter 路由 `gemini-3.8-flash`。不保存 user-settings/config 全文或任何 credential value。

## 红绿证据

- 新增观察者/反思者/Recall 时区测试先红：定向运行 `test_f1_language.py` 与 `test_client_contract.py` 得到 **5 failed, 9 passed**。失败归因分别是提示缺少时区/本地 now、Recall 请求缺 `cue_context.current_timezone`；两个提醒缺陷为 DST gap 未拒绝和附带尾文 ISO 偏移被丢弃。该组由 `f4_a_wiring` 接管产品接线。
- 新增 IntentBridge 时区传递测试先红：`test_f4_intent_bridge_passes_user_timezone_to_reminder_service` 得到 **1 failed**，原因是构造器不接受 `config`。
- 修复后，`core/tests/unified_memory/test_reminder_automation.py -k "intent_bridge_passes_user_timezone or aware_zoneinfo_gap"`：**2 passed, 39 deselected**。
- 最终配置与提醒专项（使用唯一 C 盘 `ATLAS_DATA_DIR` 与 `--basetemp`、停用 cacheprovider）：`core/tests/test_config.py core/tests/unified_memory/test_reminder_automation.py`：**51 passed in 7.88s**。
- 运行器：`D:\Atlas\core\.venv\Scripts\python.exe`。测试参数：`-m pytest -q -o addopts= -p no:cacheprovider --basetemp <unique C:\Users\25011\AppData\Local\Temp path>`。未触碰 `D:\Atlas\data`、`D:\MemoryOSData`。
- `ruff check` 覆盖本轮 Atlas 时区、提醒、IntentBridge、配置及其测试和冒烟脚本：**All checks passed**。冒烟脚本 `--help` 通过；这不代表模型请求或真实 Automation 效果。
- 首次直连工具脚本曾传 `tool_choice` 给 Atlas `ModelRouter`，但 Hermes `call_llm` 签名不支持该参数；Python 参数绑定在 provider 请求前失败，未发送模型请求。该路径已由 Observer 端到端脚本取代。
- Observer 端到端真实模型请求（一次）：`gemini-3.8-flash` / `memory_observe`，5664 输入、194 输出 tokens。真实抽取生成 `facet=COMMITMENT`、`valid_from=2026-10-10T09:00:00+08:00`，时区为 `Asia/Shanghai`；用户源事件已 ACK 到隔离 MemoryOS。该轮脚本因没有产生 `INTENT` 而在 Observer 检查处停止，故派生观察未提交、未创建 unified intent、未创建 Automation。脱敏证据：[f4_a_observer_attempt_1.json](f4_a_observer_attempt_1.json)。这确认了真实本地 `valid_from`，不代表 Automation smoke 通过。
- wiring 稳定其通用“明确授权的未来提醒/通知 → INTENT”提示规则后，用同一自然输入“明天上午9点提醒我交报告”再次跑真实 Observer→MemoryOS HTTP→IntentBridge→AutomationStore，结果 **通过**：`gemini-3.8-flash` / `memory_observe` 产出 `facet=INTENT`、`valid_from=2026-10-10T09:00:00+08:00`；隔离 MemoryOS 保存来源支持的 intent，Atlas AutomationStore 保存本地触发时间 `2026-10-10T09:00:00+08:00`。模型用量 6080 输入、219 输出 tokens。脱敏证据：[f4_a_automation_smoke.json](f4_a_automation_smoke.json)。
- 两次真实 Observer 模型调用合计：**11744 输入、413 输出、12157 tokens**（5664+6080 输入；194+219 输出）。首次分类失败与第二次完整链路成功均保留记录；不把首次结果冒充成功，也不把单测当成真实模型效果。
- 依总控裁定，保留本地被忽略的 `core/uv.lock`，不再恢复或提交。`uv lock --offline --no-upgrade` 曾因 root lock 漂移重解锁文件；原字节无副本/hash，无法证明恢复。当前只读状态：6055 行 / 800930 bytes，SHA-256 `145D629D998D876B2D85EB89FEE9968BA21D682AA5DC6A0ECE968A6A28460492`；`.gitignore:18` 排除该文件。此偏差已如实登记，未运行 `uv sync` 或重装依赖。

## 交接与未完成验收

1. `f4_a_wiring` 报告 `test_f1_language.py` **12 passed**，且相关 F401/F821、`git diff --check` 检查通过；总控负责审阅其接线改动并统一复跑 Atlas/MemoryOS 验收。
2. 本实现者负责的配置与提醒专项为 **51 passed in 7.88s**；总控已报告 Atlas 全集 **344 passed / 2 skipped**。MemoryOS 最终专项验收结果待总控记录。
3. 总控完成 diff 审阅、复跑及统一验收后决定提交。本实现者不提交或推送。
