# F1-D scenario actions (C-owned adapters)

日期：2026-10-09  
状态：adapter 初版已实现并通过独立单测；等待 runner 集成复核与总控真实隔离验收。

## 实现边界

唯一产品外文件为 `scripts/memory_v1/scenario_actions.py`；独占测试为 `scripts/memory_v1/test_scenario_actions.py`。适配器只使用 runner 提供的 loopback Atlas、隔离 MemoryOS、隔离 workspace 与身份校验后的生命周期接口。每个结果都带 `status`、请求、HTTP observations 与读回；`failed` / `unsupported` 会由 runner 记为执行错误。

已接入 pause/resume capture revision 控制、可用性校验后的模型切换、唯一真实记录的 correction、MemoryOS HARD_ERASE 完整 `preview → request → owner authorization → execute → verify`、S2 graceful restart、S30 owned crash/start。S30 只在隔离 workspace 实际存在 `file1.md` 时继续，并忽略 payload 中的 PID 和 `completed_steps`。

S29 `audit_reminder_state(ctx)` 只读 AutomationStore、MemoryOS INTENT、真实 WS tool-call 摘要和该 automation 的 run receipts。它要求 turn-1 相对隔离 baseline 出现唯一新提醒且有真实提醒类 tool-call，turn-2 同 ID 被删除或转入取消/禁用状态且有真实取消类 tool-call，turn-3 同 ID run receipt 端点可读且为空。缺少任一状态会失败，不将最终空列表当成取消成功。当前 Atlas `/api/automations/{id}/runs` 对已删除 automation 返回 404，因此被删除记录无法通过当前 API 证明 receipt 为空；本适配器会保留该证据为失败，不把 404 推断成零 receipt。

## 验证

行为单测：**17 passed**。首轮 pytest 使用共享默认临时根时遇到 `pytest-current` 清理权限异常；后续运行使用独立 `--basetemp`，并为 Atlas/MemoryOS/Hermes 显式设置 D:\Temp 隔离根。最终输出与 JUnit：

- 命令：`core\.venv\Scripts\python.exe -m pytest scripts\memory_v1\test_scenario_actions.py -q --basetemp=D:\Temp\F1-C-actions-unit-20261009-1905\pytest --junitxml=D:\Temp\F1-C-actions-unit-20261009-1905\junit.xml`
- JUnit：`D:\Temp\F1-C-actions-unit-20261009-1905\junit.xml`
- 结果：`17 passed in 0.20s`

该轮测试使用契约 fake 验证拒绝歧义与 revision 冲突、错误模型不替代、capture 版本控制、硬擦除执行及物理/统一层验证、S30 生命周期只调用 runner-owned crash/start、S29 创建/取消/receipt 阶段条件，以及 transport exception 不输出含凭据文本。它**不是**真实模型或真实 HTTP 效果证据；真实隔离 action 抽查与总控全量门禁仍待执行。

## 后续约束

保持 runner (`eval_scenarios.py`) 由 A 唯一维护。F1-C2 全局暂停只做源码定位与最薄接线方案；产品改动须待总控确认文件所有权和接口。未提交、未推送。
