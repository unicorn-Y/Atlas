# ATLAS-U0 结果:Hermes 最新上游同步(2026-10-03)

## HEAD 变化

| | 提交 | 日期 |
| --- | --- | --- |
| upstream/main(同步目标) | `a6e75acb0dc68c99d33fe8ba421a186b6b781b7c` | 2026-10-02 |
| fork atlas(同步前) | `e287231d7906bcce5bc373d20fb2e3e1e6427220` | 2026-10-02 |
| merge-base | `aea969677c60a1bb72fe227fdfb98f196a2092cc` | 2026-10-01 |
| fork atlas(同步后) | **`27c63095b002b531b07bd6ad31da88bfe821f55f`** | 2026-10-03 |
| ahead/behind | 同步前 8/518 → 同步后 **519/0** | |

已推送 `unicorn-Y/hermes-agent:atlas`;Atlas `core/pyproject.toml` pin 已更新为 `27c63095b0`。

## 冲突文件及选择

仅 1 个:`tools/file_operations.py`。
- 保留 Atlas 4 元组 `_probe_write_target`(`encoding` 支持 UTF-16 Windows 写);
- 重放 upstream 新增的 `_refuse_introduced_json_constant` JSON 常量引入拒绝检查。

## Atlas 增强保留核查(逐项确认在合并后存在)

- `agent/turn_tool_round.py` `_apply_atlas_context_handoff` ✓(行 26)
- `agent/conversation_loop.py` `_atlas_before_model_request` 暂停闸门 ✓(行 1637)
- `agent/context_compressor.py` 固定「## Next Steps」摘要段 ✓(行 4121)
- `tools/fuzzy_match.py` `block_anchor_variable_size` 策略 + SIMILARITY_STRATEGIES ✓
- `tools/file_tools_read_tracking.py` 全读基线 ✓
- `agent/tool_guardrails.py` `_result_hash`/`_sha256` 接受多模态 envelope ✓(行 620/630)
- `pyproject.toml` openai==2.26.0 / pydantic==2.13.5 主机兼容 pin ✓
- `toolsets.py` `new_context_window` ✓
- Windows UTF-16 写修复、MCP 孤儿进程修复的测试文件全部在 ✓

## upstream 新能力(与 Atlas 相关)

- `agent/anthropic_thinking_replay.py` + `_policy.py`(Anthropic 思考回放策略)
- `agent/tool_call_batches.py`(工具调用批)、`agent/message_sanitization.py`
- turn-recovery 集群更新、desktop/CLI 大规模稳定化、git-filter 中和系列(subagent_worktree 受影响)
- Honcho 记忆插件解绑为 catalog 安装(Atlas 记忆冻结,不受影响)
- **无能力域取代 Atlas 现有实现**(browser/computer/skills_hub/curator/delegate 窗口期未被上游触碰)

## 测试

| 套件 | 结果 |
| --- | --- |
| tests/agent/test_atlas_context_handoff.py + test_tool_guardrails.py + tests/tools/test_fuzzy_match.py | 84 passed |
| tests/agent/test_context_compressor.py + write-baseline + orphan(合批) | 295 passed |
| tests/tools/test_known_file_write_baseline.py | 18 passed |
| tests/tools/test_mcp_windows_orphan_fix.py | passed(core venv) |
| tests/tools/test_file_operations.py | 67 passed / 6 failed(POSIX umask/symlink 本机环境已知失败,**合并前纯 atlas 分支同样失败**,非回归) |
| tests/tools/test_delegate.py + tests/agent/test_turn_recovery_autorecover.py | 74 passed |

## Atlas 重复实现可删除清单

无:上游窗口未触碰这些能力域,U1 的 KEEP/UPGRADE/REPLACE 由 core-refresh-map 逐项判定。
