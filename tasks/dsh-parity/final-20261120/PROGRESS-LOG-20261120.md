# 吸收进度日志（2026-11-20）

## 底账

- 来源：Codex 会话「全面拆解最新版DSH」的声明抽取表
  - `Atlas-DSH-最新TS到JS语法声明.tsv`：91,002 条
  - `Atlas-DSH-最新Python语法声明.tsv`：19,531 条
- 合计 110,533 条声明；DSH 81,553 / Atlas 28,980。
- 双向全量表：106,805 行（DSH 81,553 + Atlas 独有 25,252）。
- 行为视图：31,740 行。
- 缺口簇：370 个；按包进度：372 个。

## Wave 1（已落地）

来源包：

- `packages/sandbox/sandbox-policy`（master `2e39e704`）
- `packages/credentials/credentials`（master `2e39e704`）

新增：

- `core/atlas/safety/sandbox_policy.py`
  - `is_execution_world_path`
  - `resolve_additional_writable_roots`
  - `resolve_execution_policy` / `render_policy_context`
  - 比 DSH 更严：拒绝 Windows 单根路径（`\foo`），按路径自身拼写判断 POSIX/Windows，适配远程执行世界。
- `core/atlas/models/credential_grammar.py`
  - `credential_ref` / `is_credential_ref_name` / `is_credential_key_segment`
  - `credential_key` / `parse_credential_key` / `credential_key_scope` / `credential_key_id`
  - `normalize_api_key` / `require_api_key` / `redact_api_key`
  - 比 DSH 多：结构化拒绝原因、日志安全脱敏。

接线（不是死代码）：

- `core/atlas/models/__init__.py`
  - `set_model_api_key`：保存前校验并 trim，非法字符直接拒绝。
  - `update_provider`：项目/全局网关密钥同样校验并 trim。
- `core/atlas/windows_job_sandbox.py`
  - `MODES` 改为引用统一常量。
  - `run_in_job` 拒绝相对路径/NUL 的 cwd。

测试：

- `core/tests/test_sandbox_policy_primitives.py`
- `core/tests/test_credential_grammar.py`
- 连同既有 `test_windows_job_sandbox.py`：**69 passed**。

真实进程验证：

```
api_key: ApiKeyVerdict(ok=True, value='sk-live-abc', reason=None)
key: llm-pi-ai/route-1
path ok: True | relative: False
policy: SandboxExecutionPolicy(mode='workspace-write', workspace_root='C:/Atlas', additional_writable_roots=('C:/Atlas/tmp',))
reject: invalid API key: illegal_characters
run_in_job reject: sandbox cwd must be an absolute execution-world path without NUL bytes
```

进度回填：全量表 11 行从 `未定位/缺失` 改为 `已吸收`，`吸收进度-按包` 同步刷新。

## 下一波候选（按缺口表）

1. `packages/sandbox/sandbox-windows-acl`（P0，Windows ACL 写限制）
2. `packages/credentials/credentials-local`（P0，凭据文件权限/原子写）
3. `packages/interaction/user-approval`（P0，审批策略）
4. 产品可见：`client-ui-stats`、`client-ui-schedule`、`ui-sidebar-documentpreview`
5. 大块：`experimental/client-ui-forge`、`client/ui-chat`、`experimental/inspector`

每波都按同一流程：读 DSH 固定提交源码 → 在 Atlas 现有入口落地 → 单测 → 真实进程触发 → 回填进度表。