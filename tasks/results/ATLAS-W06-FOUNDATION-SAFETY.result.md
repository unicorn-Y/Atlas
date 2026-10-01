# ATLAS-W06-FOUNDATION-SAFETY 执行结果

日期：2026-10-01
基线：main（任务书开始前 `git pull origin main --ff-only` 成功）
上游：NousResearch/hermes-agent，实际参考提交 `663362680b6ffa4fbffeb58f6682564239a1953b`；源码搬运登记见 `docs/plan/VENDORED.md`，MIT 声明见 `THIRD_PARTY_NOTICES.md`。
协议：1.7 → 1.8。
范围：后端 §0–6；未修改 `frontend/`、`backend-adapter/`、`core/atlas/origin_guard.py`。

## 分节交付

| 节 | 提交 | 交付与主要文件 |
| --- | --- | --- |
| §0 | `b605d4d` | Worker 继承父 run 模型；web 提取连接绑定通过 DNS 校验的 IP；忽略 pytest 临时目录。来源移植 `core/atlas/tools/ssrf_transport.py`。 |
| §1 | `3955704` | Claude 提示缓存断点、TTL、网关标记兼容及缓存用量字段；`core/atlas/agent/prompt_caching.py`、`prompt_cache_boundary.py`。 |
| §2 | `d3c4aad` | 工具输出限制/截断、持久结果、模型价格估算和 usage API；`core/atlas/tools/output_limits.py`、`output_truncate.py`、`core/atlas/agent/results.py`、`core/atlas/usage_pricing.py`、`usage.py`。 |
| §3 | `42415f0` | 错误分类、重试、fallback 冷却和模型切换；`core/atlas/agent/error_classifier.py`、`retry_utils.py`、`fallback_cooldown.py`。 |
| §4 | `02d647d` | 危险操作规则、智能审查、威胁扫描、安全策略和执行前检查点；`core/atlas/safety/`。 |
| §5 | `7e636fa` | 代码改动后缺少验证证据时提醒；`core/atlas/agent/verification_stop.py`。 |
| §6 | `590f063` | 记忆候选来源与外部候选人工确认；本地 sherpa-onnx/SenseVoice、VAD ASR；`core/atlas/memory/`、`core/atlas/asr.py`。 |

§0–6 各节各有一个实现提交。后续集成修正提交待记：本结果文档提交会提供最终 SHA。工作区原有未跟踪 `design/atlas-glass-prototype.html` 与本任务无关，未改动。

## 偏差与已知限制

- §1：缓存控制仅对 Claude 路由应用；Hermes 专属缓存构造器测试未全部移植。当前用户模型为 DeepSeek/OpenAI 兼容入口，不支持 Anthropic cache control，不能从本次模型连接测试推导出缓存命中。任务要求的真实模型 5 轮命中率没有完成。
- §2：子任务 usage 未单独接入记录；价格表为明确列出的模型子集，未知价格返回 `null`。
- §3：采用 provider-neutral 的分类子集，未搬入 H 的 1491 行全部规则；未搬 rate-limit tracker；自动重试有短上限。429/402/503 等以 mock 测试覆盖，未向真实网关注入故障。
- §4：危险规则及 threat pattern 是 H 的适配子集；`safety.trusted_paths` 可配置但当前未参与执行决策。一次真实模型试跑中，隔离副本 `config/atlas.toml` 的 filesystem MCP 参数仍指向 `D:/Atlas`。模型随后启动 `Get-ChildItem -Path C:\ -Filter note1.txt -Recurse`。我立刻停止该试跑及关联搜索/服务进程，并核对这些进程均已退出。没有观察到仓库文件被改动，但不能证明该只读递归搜索在停止前没有读取到盘上内容。由于 MCP 根路径和 run workspace 不一致，未继续执行真机场景；任务要求的三个真机场景均未验收通过。必须先修正隔离服务配置并确保 MCP 工具只可访问合成测试目录，再重新验收。
- §5：验证证据来自本轮工具记录；未接入独立持久化证据库。
- §6.1：当前保守地把含工具结果上下文抽取的候选标记为 external；strict 扫描器规则范围有限。
- §6.2：本地 sherpa-onnx 真实模型通过 ASR WebSocket 识别官方中文样例，结果为“早上九点至下午五点”，漏掉样例开头短语；真实麦克风输入未测（测试机未安装 sounddevice，且没有录入真人语音）。因此不能声称麦克风验收通过。
- §0：早先 pytest 运行留下的 `core/.pytest-*` 本地临时目录仍在；忽略规则已加入，但清理被当前环境阻止。最终全量运行使用 AppData 下的 basetemp，没有再向仓库写测试临时数据。
- 实际模型连接：隔离 Atlas 服务使用当前用户配置的 `deepseek-v4.1-flash` 请求 `/api/settings/test-connection` 成功。该项只证明模型凭据/网关连接，不等于 W06 新功能真机场景验收。

## 补充集成修正

全量测试暴露并已修复：Agent 缺失 `re` 导入；mock run context 无 `model` 属性时访问失败；`tool_call` 事件队列发送代码位于不可达分支；W06 升到协议 1.8 后两处旧测试断言仍期待 1.7。相应更改在最终补充提交中。

## 全量测试

后台完整运行：`719 passed, 6 skipped in 163.45s (0:02:43)`（725 项收集，无失败）。运行日志：`%LOCALAPPDATA%\Atlas-W06-validation\pytest-final-group.log`；临时基目录位于同一 AppData 验证目录。

## 手动复核

1. 用全新隔离 `ATLAS_DATA_DIR` 启动开发后端，检查 `/api/usage`、`/api/safety`、`/api/asr/status`。
2. 确保 MCP filesystem server 唯一允许根是独立合成目录、MCP git/brave-search 未启动，run 的 `allowed_paths` 仅为该目录，然后再按 taskbook §4 三个场景逐一记录审查事件和文件状态。
3. 安装 `sherpa-onnx` 后通过 `/api/asr/download` 拉取模型，再用测试麦克风验证中文分句及 partial/final 消息。

实现和自动测试完成；由于 §4 真机场景和真实麦克风验证未完成，交付状态是“实现完成，真机验收未完成”，不能标记为完整验收通过。

