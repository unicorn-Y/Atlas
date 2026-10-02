# C5 施工契约（第二施工组内部对接规范）

分支：`zcode/c5-models-parallel`（worktree `D:\Atlas-c5`）。所有施工只在此 worktree。
禁止：改 `tasks/CURRENT.md`、merge main、git commit/push（主控统一提交）、碰 `design/`、放宽 OriginGuard。
热文件规则：`hermes_runtime.py` 只归 B3；`server.py` 只允许 B4 加一行 include；`App.tsx`/`useAtlasStore.ts` 只归 B5（且必须最小增量改动）。
UI 文案全中文。禁止过度防御/兼容层/大测试矩阵。

## 1. 数据模型（data/user-settings.json，向后兼容）

现有键不动：`custom_models, selected_model, gateway_base_url, api_key, compression_model`。
新增键：

```jsonc
{
  "providers": {
    "<provider_id>": {
      "base_url": "可选，覆盖 catalog 默认",
      "keys": [ { "id": "k_ab12cd", "label": "主密钥", "added_at": "ISO" } ]  // 只有元数据，密钥原文进 keyring
    }
  },
  "reasoning_stages": { "enabled": false, "planning": "high", "execution": "medium", "verification": "high" }
}
```

keyring：复用 `core/atlas/telegram.py` 的 `KeyringCredentialStore`（service=`"Atlas"`），
account = `atlas.provider.<provider_id>.key.<key_id>`。密钥原文永不进 settings/日志/API 响应/结果文件。

custom_models 条目扩展（全部可选，缺省=现状行为）：

```jsonc
{
  "id": "...", "name": "...", "provider": "...", "litellm_model": "...", "category": "...",
  "custom": true, "max_output_tokens": 8192, "price": {"input":0.1,"output":0.2,"cached_input":0.01},
  "hermes_provider": "deepseek",        // catalog id；缺省 → 完全走现有 gateway 行为（红线）
  "native_model": "deepseek-v4.1-flash",// 原生模型 id（不带 litellm 前缀）
  "base_url": null,                     // 每模型覆盖；否则 providers.<pid>.base_url；否则 catalog 默认
  "capabilities": { "context_window":128000, "max_output_tokens":8192,
                    "supports_vision":false, "supports_tools":true, "supports_reasoning":true }
}
```

## 2. Provider catalog（B1：core/atlas/models/catalog.py）

16 家，字段：`id, label(中文), hermes_provider, api_mode("openai"|"anthropic_messages"), default_base_url, docs_url, notes`。
hermes profile 已实测存在：anthropic(anthropic_messages)、google、openrouter、deepseek、kimi-coding、zai、
alibaba(dashscope intl)、minimax(anthropic_messages)、stepfun、xiaomi、ollama、custom。
没有 profile 的走 openai-compat：siliconflow(https://api.siliconflow.cn/v1)、volcengine-ark(https://ark.cn-beijing.volces.com/api/v3)、
lmstudio（hermes 识别 provider=="lmstudio" 特殊路径）、openai、custom。
qwen 用 `hermes_provider="alibaba"` 但 default_base_url 用国内 `https://dashscope.aliyuncs.com/compatible-mode/v1`（base_url 覆盖 profile 默认）。
`docs_url` 每家查当月官方文档填真实链接（2026-10），写入代码注释和对照表。
导出：`PROVIDERS: list[dict]`, `get_provider(pid) -> dict|None`, `api_mode_for(pid) -> str`。

## 3. 模块 API

### B1 core/atlas/models/reasoning_effort.py（整文件拷贝自 hermes `agent/reasoning_effort.py`@e287231）
文件头注明来源与 commit（MIT，登记 THIRD_PARTY_NOTICES.md + docs/plan/VENDORED.md）。

### B1 core/atlas/models/models_dev.py（拷自 hermes `agent/models_dev.py`@e287231，小改）
- 缓存目录改注入：默认 `atlas.config.get_config().db_path.parent / "cache" / "models_dev"`（保证 tests 隔离：从 config 取）。
- `requests` 不可用（Atlas 无此依赖）→ 改 `httpx` 同步 get（~5 行）。
- 剥离 hermes_cli.config / hermes_constants 依赖（get_hermes_home→注入目录；openrouter_variant_base 内联）。
- 保留：ETag 条件 GET、5 级缓存、`fetch_models_dev()`、`get_model_capabilities(provider, model, *, allow_network=False)`、`PROVIDER_TO_MODELS_DEV`。

### B1 ModelManager 扩展（core/atlas/models/__init__.py，保持现有公共 API 一字不动）
新增方法（B2/B3/B4 依赖这些签名）：
```python
def provider_config(self, provider_id: str) -> dict           # {"base_url":..., "keys":[...]}，无则 {}
def update_provider_config(self, provider_id: str, base_url: str | None) -> None
def add_key(self, provider_id: str, secret: str, label: str = "") -> dict   # 返回 {"id":...,"label":...}
def remove_key(self, provider_id: str, key_id: str) -> None
def list_keys(self, provider_id: str) -> list[dict]           # 合并池状态：id,label,cooldown_until,last_error,request_count（无原文）
def resolve_api_key(self, provider_id: str) -> str | None     # 池中首个非冷却 key（keyring 读）→ 无则 None
def credential_pool(self, provider_id: str) -> Any | None     # AtlasCredentialPool；该 provider keys<2 时返回 None
def update_model(self, model_id: str, patch: dict) -> dict    # M6，仅 custom 模型；key 不在此改；ValueError 未知 id
def delete_model(self, model_id: str) -> None                 # M6；若删除的是选中模型则切到列表第一个
def list_models(self)  # 附加字段（additive）：capabilities(合并 models.dev + 手填 override)、reasoning_efforts
```
`list_models` 附加 capabilities 的合并顺序：models.dev（allow_network=False）← 模型条目手填 `capabilities` 覆盖。
新增 `reasoning_efforts`：来自 vendored reasoning_effort `route_supported_efforts(hermes_provider, native_model)`（可得时）。

### B2 core/atlas/models/credentials.py — AtlasCredentialPool
实现 hermes 池协议子集（调用点已核实）：
- 属性：`provider`（hermes provider id）；`entries()` → list[entry]；`current()`；`has_credentials()`；`has_available(model=None)`；`next_available_at(model=None)`（epoch 秒）；`select(model=None)`；`peek()`；`reclaim(id, model=None)`；`mark_exhausted_and_rotate(*, status_code=None, error_context=None, api_key_hint=None, credential_id=None, failure_reason=None, model=None) -> entry|None`。
- entry：`id, runtime_api_key(属性→keyring), base_url, label, last_status("ok"|"exhausted"), last_error, cooldown_until(epoch), model_cooldowns(dict), request_count`。
- 冷却矩阵（参照 hermes agent/credential_pool.py@e287231，头注写来源）：429→1h 或 error_context 里的 reset_at/retry-after；401/403→5min（billing 语义 1h）；默认→1h；唯一可用 key 非 billing→60s。model 级 429 只冷却 (key, model)。
- 状态持久化进 settings 的 providers.<pid>.keys[i]（cooldown_until/last_error/request_count）。
- select() 递增 request_count。
- 测试（core/tests/test_model_credentials.py）：①key1 429 → mark_exhausted_and_rotate 返回 key2 且 key1 进入冷却；②冷却到期（fake clock/注入 now）后恢复；③协议兼容：import `agent.agent_runtime_helpers.recover_with_credential_pool` 用 stub agent（pool+api_key/base_url 属性）走一次 429 路径断言换 key 生效。

### B3 core/atlas/models/reasoning_stages.py + cache_diagnostics.py
```python
# reasoning_stages.py
DEFAULT_STAGES = {"planning": "high", "execution": "medium", "verification": "high"}
def load_stage_config() -> dict          # settings["reasoning_stages"]，缺省合并 DEFAULT_STAGES+enabled False
def save_stage_config(cfg: dict) -> None # 校验档位 ∈ EFFORT_LADDER
def effort_for_phase(cfg: dict, phase: str) -> str | None  # cfg 未 enabled → None；phase ∈ {"planning","execution","verification"}
```
```python
# cache_diagnostics.py
def record_layer_hashes(conversation_id: str, system_prompt: str, tools_signature: str, history_signature: str) -> dict
    # 返回 {"system":sha16,"tools":sha16,"history":sha16}；每会话保留最近 8 次（进程内 deque）
def explain_cache_drop(conversation_id: str, current: dict, cached_input_tokens: int, input_tokens: int) -> str | None
    # 与上一次可比请求比对：tools 变→"工具定义变了（可能是 MCP 服务器重连）"；system 变→"系统提示词变了"；
    # history 变→"历史前缀变了（新消息/压缩/分支）"；无法本地证明→"缓存未命中原因未知（可能超过缓存有效期）"
    # 仅当命中率明显下降（当前命中≈0 且上次>0，或命中率降幅>0.5）才给原因，否则 None
```

### B3 引擎接线（唯一有 hermes_runtime.py 编辑权，单个 commit message 含 "C5 integration touchpoint"）
全部改动压在 run_turn 的 agent 构造段（:445-542）与 run_sync 的 usage emit（:668-681）附近，目标 ≤35 行 diff：
1. **M1**：model_config 有 `hermes_provider` 时：`provider=<hermes_provider>`，`api_mode=<catalog.api_mode_for>`，
   `model=<native_model or litellm_model>`，`base_url=<模型base_url或provider配置或catalog默认>`，
   `api_key=<settings.resolve_api_key(pid)>`；无 hermes_provider → 现行为逐字节不变。
   构造参数追加 `credential_pool=<settings.credential_pool(pid)>`（None 时 hermes 自行忽略）。
2. **L8**：`reasoning_config` 改由 reasoning_stages 计算：plan_mode 或首轮（history 为空）→ planning 档；
   否则 execution 档；stop-gate 验证轮 → verification 档（先 grep hermes `agent/turn_stop_gates.py` 与
   `_atlas_before_model_request` 在 hermes-agent@e287231 的调用点：若每请求前调用，则在该 hook 里按
   `agent._verification_stop_nudges/_pre_verify_nudges>0` 切 verification 档——evidence-based，别猜）。
   关闭（enabled=False）时必须与现行为完全一致。
3. **M5**：run_sync 里拿到 usage 后：调用 record_layer_hashes（system=system_message 或 agent 系统提示，
   tools=enabled toolsets 签名，history=len+末条消息 hash）→ explain_cache_drop → 非空时并入
   `emit({"type":"run_usage", "usage": {..., "cache_miss_reason": reason}})`。
4. 相关聚焦测试：core/tests/test_reasoning_stages.py、test_cache_diagnostics.py（单元）+ 在现有
   test_hermes_runtime_e2e.py 风格上加 1 条「分阶段档位随请求变化」（fake agent）。

### B4 core/atlas/models/routes.py + server.py 一行接线
`models_router = APIRouter()`，全用 `async def`；访问 manager 用
`from atlas import server as _server; mgr = _server.model_mgr`（函数内 import 防循环）。
端点（全部走 OriginGuard，勿放宽；响应永不包含密钥原文）：
- `GET  /api/providers` → catalog + 每家 {base_url, key_count, keys:[{id,label,cooldown_until,last_error,request_count}], configured}
- `PUT  /api/providers/{pid}/config` {base_url?: str|null}
- `POST /api/providers/{pid}/keys` {secret: str, label?: str} → 201 {id,label}
- `GET  /api/providers/{pid}/keys`；`DELETE /api/providers/{pid}/keys/{key_id}` → 204
- `PUT  /api/models/custom/{model_id}`（M6 编辑：name/base_url/litellm_model/native_model/hermes_provider/max_output_tokens/price/capabilities；key 不在此端点）→ 200 更新后条目
- `DELETE /api/models/custom/{model_id}` → 204
- `GET/PUT /api/models/reasoning-stages`
- `POST /api/models/test` {model_id} → 用该模型 provider 的 base_url+resolve_api_key 走 litellm.acompletion max_tokens=2（provider_id 无 key 时 400）
server.py 接线：`app.include_router(...)` 单独 commit "C5 integration touchpoint: mount models router"。
测试 core/tests/test_models_routes.py：编辑/删除/加 key/列表无原文/reasoning-stages 读写/OriginGuard 恶源 403/未知 id 404/409。
沿用 test_server.py:32-58 的 isolated_atlas_config + ASGITransport 范式。

### B5 前端 + backend-adapter
- types.ts：`ProviderCatalogEntry, ProviderState, KeySlotInfo, ReasoningStagesConfig, CustomModelUpdateRequest`；
  `ModelInfo` 追加可选 capabilities/reasoning_efforts；`UsageRow`/run.usage 事件数据追加 `cache_miss_reason?: string`。
- client.ts 新方法：`getProviders, updateProviderConfig, addProviderKey, listProviderKeys, removeProviderKey,
  updateCustomModel, deleteCustomModel, getReasoningStages, saveReasoningStages, testModelById`。
- mock.ts 同步补 mock 兜底。
- SettingsPage.tsx：重构为「先选服务商（16 家网格）→ 按 provider 显示所需字段（base_url 预填 catalog 默认可改、
  模型 id、密钥（password 框，多密钥列表可增删、显示冷却/状态徽标，绝不回显原文）、价格、能力）」；
  已有模型行加「编辑」「删除」；「按阶段分配思考量」区块：开关默认关 + 三档 select（规划/执行/验收）。
  大组件拆到 `frontend/src/renderer/pages/models/`（ProviderGrid/ModelForm/KeyManager/ReasoningStages）。
- UsagePanel.tsx：有 cache_miss_reason 的记录显示原因（列/详情均可）。
- useAtlasStore.ts：新增 state+action（providers、reasoningStages、updateCustomModel/deleteCustomModel），
  不动现有 action 逻辑；App.tsx 只改 SettingsPage/UsagePanel 的 props 传递两处。
- 验证：`npm run test:adapter`、现有 vitest 全绿、`npx tsc -p tsconfig.renderer.json --noEmit`。
  新组件如有逻辑（如档位校验）配 1 条 vitest。

## 4. 提交与验证（主控负责）
每 lane 一个 commit；热文件接线单独 commit。测试命令：
`cd /d/Atlas-c5/core && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "$TEMP/pt-<lane>" tests/test_<相关>.py`
不跑全量 pytest。前端四项最后统一跑。VENDORED 登记与 THIRD_PARTY_NOTICES 由 B1 完成。
