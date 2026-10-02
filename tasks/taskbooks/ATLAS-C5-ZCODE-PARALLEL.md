# ATLAS-C5-ZCODE-PARALLEL：模型层并行施工线

> **这是 ZCode 的独立施工任务，不是 main 当前任务。**
> Codex 正在 main 上做 C3；你负责 C5 模型层。两条线并行，禁止互相覆盖。
> 施工分支：`zcode/c5-models-parallel`。Hermes 如需改内核，使用 Hermes fork 的同名分支，**不要直接 push atlas 分支**。

先读：
- `tasks/ZCODE-CURRENT.md`
- `docs/plan/00-MASTER-PLAN.md`
- `docs/plan/CORE-PARITY.md`：L8、M1、M2、M5、M6
- `docs/plan/EXECUTION-GUIDE.md`
- 原任务书 `tasks/taskbooks/ATLAS-C5-MODELS.md`

## 目标

在不依赖 C3/C4 的前提下，把 C5 模型层主体做完：
- M1 服务商与模型能力元数据
- M2 多密钥轮换/冷却
- L8 分阶段 reasoning effort
- M5 缓存未命中原因
- M6 编辑已有模型

完成后只 push 你的独立分支并写结果，不 merge main，等上游验收。

## 并行开发规则

你现在不是搬运工，本任务里你是**第二施工组主控**。

- 如果你的环境支持子代理，按文件/模块并行开多个；如果不支持，就自己直接施工。
- 优先把工作拆成：模型后端 / credential pool / reasoning+usage / 前端模型设置 / 聚焦测试。
- 每组只改自己负责文件；会改同一个共享文件的工作合并到同一组。
- 不为理论异常堆 fallback、抽象层、兼容层。
- 不搞大测试矩阵；聚焦测试 + 最后一轮必要检查即可。

## 冲突隔离

### 优先负责的区域
- `core/atlas/models/**`
- 新增的模型/provider/credential/usage 辅助模块
- model/usage 相关测试
- `frontend/src/renderer/pages/SettingsPage.tsx`
- `frontend/src/renderer/pages/UsagePanel.tsx`
- model 专用的新前端组件
- `backend-adapter/src/types.ts` / `client.ts` 中**仅模型相关**接口
- 模型相关配置文件

### C3 正在频繁改的共享热文件
尽量不要碰：
- `core/atlas/agent/**`
- `core/atlas/engine/hermes_runtime.py`
- `core/atlas/server.py`
- `frontend/src/renderer/App.tsx`
- `frontend/src/renderer/store/useAtlasStore.ts`
- 会话/权限/运行事件/子 Agent UI

如果 C5 真正接线必须碰共享热文件：
1. 改动压到最小；
2. 单独一个 commit，message 带 `C5 integration touchpoint`；
3. 结果文件列出这些文件，方便后面人工/上游合并；
4. 不为了避免一个小接线点而自造第二套架构。

## 1. M1：服务商与原生参数

优先复用 Hermes：
- `providers/`
- `agent/provider_registry.py`
- `agent/models_dev.py`
- `agent/reasoning_params.py`

Atlas 的 ModelManager 现在仍偏 OpenAI-compatible。改成“服务商 + 模型”配置，而不是只存一个 LiteLLM 字符串。

至少支持：
- OpenAI
- Anthropic
- Google/Gemini
- OpenRouter
- DeepSeek
- Kimi/Moonshot
- GLM/智谱
- Qwen/通义
- MiniMax
- Step/阶跃
- MiMo
- 硅基流动
- 火山方舟
- Ollama
- LM Studio
- 自定义 OpenAI-compatible

要求：
- 原生参数映射尽量直接复用 Hermes；Atlas 不再另写一套 provider 大表。
- 模型元数据包含：上下文上限、输出上限、视觉、工具调用、reasoning 能力、价格/缓存字段。
- models.dev 能给的优先用；Atlas 本地只保留必要 override。
- 保住用户现有的 OpenAI-compatible 中转用法，不要求迁移才能继续用。
- 当月参数只以官方文档/Hermes 当前实现为准，不凭旧记忆。

前端“添加模型”改成先选 provider，再填该 provider 真正需要的字段；不要一屏把所有参数全摊开。

## 2. M2：多密钥轮换

直接参考/复用 Hermes：
- `credential_pool.py`
- `credential_pool_admin.py`
- `credential_pool_model_cooldowns.py`

要求：
- 一个 provider 支持多个 key；
- 429 / quota exhausted 后切下一个；
- 被限 key 进入冷却，到期恢复；
- 设置页显示 key 槽位状态/冷却，**永远不显示完整 key**；
- 新代码不要把 key 写日志、Usage、结果文件。

如果 Atlas 当前 secret 存储没有系统 keyring，就先复用项目已有 secret/keyring 机制；不要为了这一项搭复杂凭据平台。

## 3. L8：分阶段 reasoning effort

只做简单、实用的一层：
- 默认关闭；
- 开启后分三档：planning / execution / verification；
- plan/首轮用 planning；
- 正常工具执行用 execution；
- stop gate / 完成前验证用 verification；
- 关闭时保持用户当前 reasoning 逻辑完全不变。

优先改 Hermes 现有 reasoning 参数入口；如果 C3 同时正在动 Hermes 核心文件，就在 Hermes `zcode/c5-models-parallel` 分支完成，不碰 `atlas` 分支。

## 4. M5：缓存未命中原因

不要建复杂缓存诊断系统。

每次 provider 请求只记录稳定层 hash：
- system prompt
- tool definitions
- history/prefix

当 cache hit 明显下降/为零且上一请求有可比前缀时，给出最可能原因：
- system 变了
- tools 变了
- history/prefix 变了
- TTL/服务端未知（无法从本地证明时明确“未知”）

Usage 页能看到这次调用的 cache miss reason 即可。

## 5. M6：编辑已有模型

已有 custom model 不再只能新增。

至少可编辑：
- 显示名
- provider
- endpoint/base URL
- 模型名
- max output/context
- reasoning/vision/tool capability flags
- price/cache price
- key：只允许重新填，绝不回显旧值

保存后下一次请求生效；正在运行的任务不用热替换。

## 最小验证

只做：
1. provider mapping 聚焦测试：挑 OpenAI-compatible + DeepSeek + Qwen + GLM + Anthropic/Google 的代表用例，不要“一家一套巨大矩阵”；
2. credential：key1 429 → key2；冷却恢复 1 组；
3. reasoning 三阶段 1 组；
4. cache miss reason 1–2 组；
5. 编辑模型 1 组后端 + 1 组前端；
6. 相关后端聚焦测试；
7. 前端 renderer tsc、electron tsc、Vitest、Vite build 各一次。

**不要跑 Atlas 全量 pytest。** 因为 main 上的 C3 正在并行变化；全量等 C5 合并 main 后统一跑。你的分支只证明 C5 自己可合并。

不用真实模型，不发真实 provider 请求；用假服务校验 request body 和 usage parsing。

## 交付

在你的 Atlas 分支写：
`tasks/results/ATLAS-C5-ZCODE-PARALLEL.result.md`

必须写：
- Atlas branch/head
- Hermes branch/head（如有）
- M1/M2/L8/M5/M6 各做了什么
- 改了哪些共享热文件（如果有）
- 聚焦测试/前端四项
- 仍有真实缺口
- 建议 merge 顺序

然后：
- push `zcode/c5-models-parallel`
- **不要 merge main**
- **不要改 `tasks/CURRENT.md`**
- `tasks/ZCODE-CURRENT.md` 改成 `AWAITING_REVIEW`
- 通知上游规划/验收者

## 硬约束

- 禁止 reset/stash/覆盖 Codex C3 的 main 工作。
- 不放宽 OriginGuard。
- 不做安全审查功能。
- 不动 Computer Use、Browser、Voice、Memory。
- 不提前做 C4/C6。
- 速度优先，成熟实现直接接，不写缩水版。
