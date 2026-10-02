# ATLAS-C5-ZCODE-PARALLEL 结果

- 日期：2026-10-02
- Atlas branch：`zcode/c5-models-parallel`，HEAD 提交序列（基线 abbb27d）：
  - `f595110` feat(models): vendor hermes provider catalog and metadata engines
  - `49631e5` feat(models): provider configs, multi-key storage, model edit/delete
  - `80be8fd` feat(models): credential pool with rate-limit rotation and cooldown
  - `0814f39` feat(engine): C5 integration touchpoint — native routing, staged effort, cache-miss reason
  - `de8e4eb` feat(server): C5 integration touchpoint — mount models router
  - `086a887` feat(web): provider-first model settings, key slots, staged reasoning UI
  - （docs 提交见文末）
- Hermes branch：**未改 fork**（无需）。Atlas 依赖 pin 仍为 `unicorn-Y/hermes-agent@e287231d7906bcce5bcce…`（`core/pyproject.toml` 未动）；所有可复用件以 vendored 方式落入 `core/atlas/models/`，来源与 commit 已在文件头注、`docs/plan/VENDORED.md`、`THIRD_PARTY_NOTICES.md` 登记。
- 施工组织：主控 + 5 个子代理施工组（B1 模型核心 / B2 凭据池 / B3 引擎接线 / B4 路由 / B5 前端适配层），按文件独占划分，契约见 `tasks/C5-CONTRACT.md`。

## 各特性做了什么

### M1 服务商与原生参数（CORE-PARITY M1 ✔）
- `core/atlas/models/catalog.py`：16 家服务商目录（id/中文名/hermes provider id/api_mode/默认端点/文档链接+查证日期 2026-10-02）。
- `reasoning_effort.py`（整份拷贝自 hermes `agent/reasoning_effort.py`@e287231，程序化 diff 验证逐字一致）与 `models_dev.py`（拷贝改：requests→httpx、缓存目录注入 Atlas DATA_ROOT、剥离 hermes_cli 依赖；保留 ETag 条件 GET 与五级缓存）。
- hermes_runtime 接线：模型条目带 `hermes_provider` 时向 AIAgent 传原生 `provider/api_mode/native_model/base_url`，激活 hermes 各家 profile 的原生参数（实测：deepseek-v4.1-flash → `extra_body.thinking={"type":"enabled"}` + 顶层 `reasoning_effort`；glm-4.6 → thinking toggle；kimi-k3 → 档位钳制；anthropic/minimax → `anthropic_messages` 原生 transport）。
- 模型元数据：`list_models()` 附加 `capabilities`（models.dev ← 手填覆盖）与 `reasoning_efforts`。
- **红线**：无 `hermes_provider` 的模型条目五个构造参数与改前逐字相同，用户现有 OpenAI 兼容中转（`openai/deepseek-v4.1-flash`）零迁移；`test_hermes_runtime*.py` 既有用例全绿。
- 集成期修正：provider id 双命名空间归一 `catalog.resolve_catalog_id`（settings 按 catalog id 存，hermes id 作为别名双向可查，如 qwen↔alibaba、kimi↔kimi-coding），并加回归测试。

### M2 多密钥轮换（M2 ✔）
- `core/atlas/models/credentials.py`：`AtlasCredentialPool` 实现hermes 运行时消费的池协议子集（`entries/current/select/reclaim/mark_exhausted_and_rotate/next_available_at/has_available/has_credentials` + entry `runtime_api_key/runtime_base_url/priority`），构造期即过 hermes `_finalize_routing` 的 `credential_pool_matches_provider` 校验。
- 冷却矩阵（源常量注释指向 hermes `credential_pool.py`@e287231）：429→1h（error_context 的 reset_at/retry-after 优先）、401/403→5min、billing→1h、唯一 key 非 billing→60s；模型级 429 只冷却 (key, model)。
- 存储：密钥原文只进系统凭据库（keyring，service `Atlas`，account `atlas.provider.<pid>.key.<id>`）；settings 只留元数据与状态；接口/日志/前端/结果文件均无原文。
- 协议兼容测试直接跑真实 `agent.agent_runtime_helpers.recover_with_credential_pool`（stub agent）验证 429 换 key 生效。
- 设置页：密钥槽位列表（label/冷却剩余/最近错误摘要/调用次数），新增/删除，永不回显。

### L8 分阶段思考量（✔）
- `core/atlas/models/reasoning_stages.py`：默认关闭；开启后三档可配（规划/执行/验收，默认 high/medium/high）。
- 接线：首轮（无历史）与计划模式 → 规划档；正常执行 → 执行档；stop-gate 验证轮 → 验收档。验证轮判定证据：hermes `conversation_loop.py:1636` 每次模型请求前调用 `_atlas_before_model_request`；`turn_api_request.py:122-124` 每请求经 `_reasoning_config_for_wire(agent)` 读 `agent.reasoning_config` 实例属性——钩子内按 `_verification_stop_nudges/_pre_verify_nudges>0` 改该属性即刻生效。
- 关闭时与现行为完全一致（含 `reasoning_effort=None` 透传）。

### M5 缓存未命中原因（✔）
- `core/atlas/models/cache_diagnostics.py`：每次请求记录 system/tools/history 三层稳定哈希（每会话近 8 次）；命中率明显下降（≈0 或降幅>0.5）时对比给出原因：「工具定义变了（可能是 MCP 服务器重连）/系统提示词变了/历史前缀变了（新消息/压缩/分支）/缓存未命中原因未知（可能超过缓存有效期）」——本地无法证明时明确写未知。
- 透出：随 `run.usage` 事件到前端（`cache_miss_reason` 字段，服务端原样透传无需改）+ 落 `usage_records` 新列（旧库 PRAGMA 检查 + ALTER 迁移），`GET /api/usage` 带出，用量页展示。

### M6 编辑已有模型（✔）
- `PUT/DELETE /api/models/custom/{model_id}`：显示名/provider/端点/模型名/max output/能力标记/价格可改；密钥只能重填（走密钥槽位接口），绝不回显旧值；保存后下一次请求生效，运行中任务不热替换。
- 前端模型行「编辑/删除」；删除选中模型自动切换到列表第一个。

## 服务商对照表（参数映射 + 文档出处，查证日期 2026-10-02）

| 服务商 | hermes provider | 默认端点 | 思考/推理参数映射 | 文档 |
| --- | --- | --- | --- | --- |
| OpenAI | openai | api.openai.com/v1 | 顶层 `reasoning_effort` | platform.openai.com/docs/api-reference |
| Anthropic | anthropic（anthropic_messages 原生） | api.anthropic.com | `thinking{budget_tokens}` / 4.6+ adaptive `output_config.effort` | docs.anthropic.com/en/docs/about-claude/models |
| Google Gemini | google | generativelanguage.googleapis.com/v1beta/openai/ | `thinkingConfig{thinkingLevel}`（兼容面） | ai.google.dev/gemini-api/docs/models |
| OpenRouter | openrouter | openrouter.ai/api/v1 | `extra_body.reasoning{enabled,effort}` | openrouter.ai/docs |
| DeepSeek | deepseek | api.deepseek.com/v1 | v4+：`extra_body.thinking{type}` + 顶层 `reasoning_effort`（漏发 thinking 会 400，profile 已 always_emit） | api-docs.deepseek.com/guides/thinking_mode |
| Kimi/Moonshot | kimi-coding | api.moonshot.cn/v1 | 顶层 `reasoning_effort`（K3 词表 low/high/max，medium→high 钳制）+ thinking toggle | platform.kimi.com/docs/api/overview |
| 智谱 GLM | zai | open.bigmodel.cn/api/paas/v4 | glm-4.5+：`extra_body.thinking{type}` + 顶层 `reasoning_effort`（5.2 high/max，5.3 low→max） | docs.bigmodel.cn/cn/guide/start/concept-param |
| 通义 Qwen | alibaba（DashScope 兼容层） | dashscope.aliyuncs.com/compatible-mode/v1 | 兼容层无自动映射；`enable_thinking` 经 extra_body 透传 | help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope |
| MiniMax | minimax（anthropic_messages） | api.minimaxi.com/anthropic | Anthropic 风格 thinking | platform.minimaxi.com/docs/guides/quickstart |
| 阶跃 Step | stepfun | api.stepfun.com/v1 | OpenAI 兼容 `reasoning_effort`（订阅 Step Plan 端点 /step_plan/v1 在 notes 注明） | platform.stepfun.com/docs/zh/guides/developer/openai |
| 小米 MiMo | xiaomi | api.xiaomimimo.com/v1 | OpenAI 兼容；reasoning_content 回显规则在 hermes transport 内 | mimo.mi.com/docs/zh-CN/quick-start/summary/first-api-call |
| 硅基流动 | openai 兼容（无独立 profile） | api.siliconflow.cn/v1 | OpenAI 兼容 `reasoning_effort` | api-docs.siliconflow.cn/docs/userguide/quickstart |
| 火山方舟 | openai 兼容（无独立 profile） | ark.cn-beijing.volces.com/api/v3 | OpenAI 兼容 `reasoning_effort` | www.volcengine.com/docs/82379/1330310 |
| Ollama | ollama | 127.0.0.1:11434/v1 | `num_ctx` + 探针式 thinking 支持 | docs.ollama.com/api |
| LM Studio | lmstudio（hermes 特殊路径） | 127.0.0.1:1234/v1 | 顶层 `reasoning_effort`（60s TTL 探针） | lmstudio.ai/docs/app/api |
| 自定义兼容 | custom | 用户自填 | OpenAI 兼容 `reasoning_effort` + extra_body 透传 | — |

## 共享热文件改动（供上游合并注意）

| 文件 | 改动 | 提交 |
| --- | --- | --- |
| `core/atlas/engine/hermes_runtime.py` | +50/−10：M1 route_kwargs、L8 初始档、验证轮钩子、M5 原因注入（任务书许可的 touchpoint） | `0814f39` |
| `core/atlas/server.py` | +4：import + `app.include_router(models_router)`（touchpoint） | `de8e4eb` |
| `frontend/src/renderer/App.tsx` | 1 行（SettingsPage props） | `086a887` |
| `frontend/src/renderer/store/useAtlasStore.ts` | +89/−2 纯增量 state/action，未改既有 action | `086a887` |
| `core/tests/test_hermes_runtime_e2e.py`（C3 在改） | +50 纯追加用例，0 删改 | `0814f39` |
| `backend-adapter/src/types.ts`、`client.ts`、`tests/client.test.ts`（C3 在改） | 模型相关类型/方法/用例追加（任务书划归 C5 的区域），+225/−6 | `086a887` |
| `frontend/src/renderer/store/useAtlasStore.test.ts` | 14 行最小修补：initialize() 增加的 reasoning-stages 请求使既有 fetch 计数断言偏移 1 位，否则 vitest 全量不绿 | `086a887` |

未碰：`core/atlas/agent/**`、`hermes_policy.py`、`session_sync.py`、`ConversationActivity`、`timeline.ts`、`tasks/CURRENT.md`、`design/`。OriginGuard 未放宽（新增路由恶源 403 已测）；未提交 `frontend/scripts/.cdp.mjs`。

## 测试

后端聚焦（172 passed，0 失败）：
`tests/test_models.py(30) test_model_credentials.py(7) test_reasoning_stages.py(5) test_cache_diagnostics.py(6) test_usage.py test_models_routes.py(14) test_server.py(73) test_hermes_runtime.py(18) test_hermes_runtime_e2e.py test_origin_guard.py`
命令：`cd core && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "$TEMP/pt" <files>`。未跑全量 pytest（任务书豁免，等合并后统一跑）。

前端四项（frontend/）：
- `npx tsc -p tsconfig.renderer.json --noEmit` ✔（0 错）
- `npm run build`（含 electron tsc + renderer tsc + vite build）✔
- `npm test`（vitest）：10 files / 46 tests 全过 ✔
- `npm run test:adapter`：13 tests 全过 ✔

用例覆盖任务书最小验证集：provider 映射代表用例（OpenAI 兼容/DeepSeek/Qwen/GLM/Anthropic/Google，含 hermes profile 实测与 routes 端到端）、key1 429→key2 + 冷却恢复（真实 hermes 恢复路径）、三阶段档位（e2e fake spy 断言首轮/后续不同档）、cache miss reason（改 tools/改 system/未下降/未知四组）、编辑模型后端+前端。全用假服务/fake，未发真实 provider 请求。

## 仍有真实缺口

1. **思考内容折叠 UI 未做**：需要动 `ConversationActivity/timeline.ts`（C3 正在高频修改，冲突隔离优先）。后端 `thinking` 事件流已在，合并后补前端折叠为小改动。
2. **litellm 辅助调用仍走网关**：压缩摘要、上下文交接、MOA 参考等 litellm 调用沿用网关 base_url/key，不随服务商原生密钥切换（主链路不受影响；网关未配且仅用原生服务商时这些辅助功能不可用）。
3. **无跨三特性的一体化 E2E**：任务书示例链（多密钥 429 切换→分阶段思考→用量页原因）由三段聚焦测试分别覆盖，未串成一条；建议合并后随 C6 全量补一条。
4. Qwen `enable_thinking` 依赖 extra_body 手填透传（DashScope 兼容层无自动映射，hermes 亦无该 profile 映射）。
5. 模型级冷却对全部 provider 生效（契约要求）；hermes 原语义仅 anthropic——语义差异已在 credentials.py 头注说明。

## 建议 merge 顺序

先合 main 上的 C3（会话交互），然后本分支 rebase main 再合 C5。理由：双方都改 `hermes_runtime.py`、`test_hermes_runtime_e2e.py`、`backend-adapter/src/types.ts|client.ts`、`useAtlasStore(.test).ts`；C5 在这些文件的改动均为小而集中的 touchpoint/纯追加，后合一方 rebase 冲突小且好解。C5 分支未 merge main、未动 `tasks/CURRENT.md`。

## 修复附录（ATLAS-C5R-ZCODE-FINISH，2026-10-02）

按 `tasks/reviews/ATLAS-C5-ZCODE-PARALLEL.review.md` 的两项 blocking fix 最小补做，未扩展任何其他 C5 范围、未 merge main。

### Fix 1 — 编辑模型时 hermes_provider 别名校验（blocking fix 1）
- `core/atlas/models/__init__.py` `update_model()`：校验由 `_catalog.get_provider(...)` 改为 `_catalog.resolve_catalog_id(...)` 别名映射。前端 `buildUpdatePatch()` 回传模型已有 `hermes_provider`（qwen 模型为 `alibaba`、kimi 为 `kimi-coding`），此前会被误判「未知服务商」拒绝编辑；现在合法通过，且存储/返回仍保持运行时路由期望的 hermes id（`alibaba` 等），不归一成 catalog id。
- 回归：`tests/test_models.py::TestUpdateModel::test_update_accepts_alias_hermes_provider` — 前端同形状 payload（含 `hermes_provider: "alibaba"`）编辑 qwen 自定义模型，断言编辑成功、hermes id 原样存储与持久化。

### Fix 2 — keyring 写失败不留假 key 槽位（blocking fix 2）
- `core/atlas/models/__init__.py` `add_key()`：凭据库写入失败时不再吞错留元数据，改为回收本次新建的空服务商槽位、不追加 key 元数据、不调用 `_persist_settings()`，抛 `RuntimeError("密钥写入系统凭据库失败: ...")`；既有路由 `POST /api/providers/{pid}/keys` 的 `RuntimeError → 500` 分支原样上报，无需改路由。
- 回归：`tests/test_models_routes.py::test_add_key_keyring_failure_returns_500_without_ghost_slot` — monkeypatch `keyring.set_password` 抛错，断言 500 + 中文 detail、`GET /keys` 为空、settings 无 `providers.deepseek`、provider 列表 `configured=false`/`key_count=0`。

### 验证（聚焦运行，任务书豁免全量）
- `tests/test_models.py` + `tests/test_models_routes.py` 合并运行：**48 passed**（含 2 个新回归；两文件单独运行亦全绿：TestUpdateModel 5 passed、test_models_routes.py 17 passed）。
- 命令：`cd core && .venv/Scripts/python.exe -m pytest tests/test_models.py tests/test_models_routes.py -q --basetemp=./.pytest-tmp`。未重跑 172 全聚焦集/前端四项/全量 pytest（两处改动均为单方法内局部修改，未扩散）。
