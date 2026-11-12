"""Provider catalog — 16 家服务商的端点与接入元数据（C5 契约 §2）。

每条记录的字段：
- id: catalog id（settings/providers/<pid>、前端网格均用此 id）
- label: 中文展示名（UI 文案）
- atlas_provider: hermes 引擎的 provider id（B3 接线时传给 AIAgent(provider=...)）
- api_mode: "openai"（OpenAI 兼容 chat completions）或 "anthropic_messages"（Anthropic 原生）
- default_base_url: 国内主站默认端点；hermes profile 默认若为海外端点，由 Atlas 传 base_url 覆盖
- docs_url: 2026-10 查证的官方文档链接
- notes: 端点/思考参数说明

端点与思考参数字段已于 2026-10-02 逐家对照当月官方文档核实（链接见各条 docs_url）。
无 hermes profile 的服务商（siliconflow / volcengine-ark / openai）在 hermes 中按
通用 openai-compat 兜底（providers.get_provider_profile 对未注册名返回 None → 通用路径）。
"""

from __future__ import annotations

# 端点/思考参数查证日期：2026-10-02。
PROVIDERS: list[dict] = [
    {
        "id": "openai",
        "label": "OpenAI",
        "atlas_provider": "openai",
        "api_mode": "openai",
        "default_base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/docs/api-reference",
        # 思考参数：chat completions reasoning_effort；Responses API reasoning.effort。
        # hermes 无 "openai" 插件 profile，走内置默认路径（Atlas 现网关行为同源）。
        "notes": "chat completions 用 reasoning_effort；Responses API 用 reasoning.effort。查证 2026-10-02。",
    },
    {
        "id": "anthropic",
        "label": "Anthropic Claude",
        "atlas_provider": "anthropic",
        "api_mode": "anthropic_messages",
        "default_base_url": "https://api.anthropic.com",
        "docs_url": "https://docs.anthropic.com/en/docs/about-claude/models",
        # 思考参数：thinking: {type: "enabled"|"disabled", budget_tokens: int}（Messages API）。
        "notes": "Anthropic 原生 Messages 协议；thinking: {type, budget_tokens}。查证 2026-10-02。",
    },
    {
        "id": "google",
        "label": "Google Gemini",
        "atlas_provider": "google",
        "api_mode": "openai",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "docs_url": "https://ai.google.dev/gemini-api/docs/models",
        # 思考参数：OpenAI 兼容层 extra_body.google.thinking_config（thinkingConfig 蛇形映射）。
        # hermes gemini profile 注册名 "gemini"、"google" 是其别名；默认端点用官方 OpenAI 兼容层。
        "notes": "OpenAI 兼容层 /v1beta/openai/；思考用 extra_body.google.thinking_config。查证 2026-10-02。",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek 深度求索",
        "atlas_provider": "deepseek",
        "api_mode": "openai",
        "default_base_url": "https://api.deepseek.com/v1",
        "docs_url": "https://api-docs.deepseek.com/guides/thinking_mode",
        # 端点核实（2026-10-02）：官方文档 base_url="https://api.deepseek.com"（/v1 亦兼容，
        # hermes deepseek profile 用 /v1）。思考模式：extra_body.thinking 开关（每次请求都要带，
        # 省略默认开启并要求回传 reasoning_content）+ reasoning_effort（low/medium/high/max）。
        "notes": "thinking 开关每请求必带 + reasoning_effort；思考输出在 reasoning_content。查证 2026-10-02。",
    },
    {
        "id": "qwen",
        "label": "通义千问 Qwen",
        "atlas_provider": "alibaba",
        "api_mode": "openai",
        # hermes alibaba profile 默认是海外 dashscope-intl；国内产品目录用国内主站（base_url 覆盖 profile 默认）。
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "docs_url": "https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope",
        # 思考参数：extra_body.enable_thinking（Qwen3 系思考模型，开启时必须流式）+ thinking_budget。
        "notes": "OpenAI 兼容模式 /compatible-mode/v1；enable_thinking + thinking_budget。查证 2026-10-02。",
    },
    {
        "id": "kimi",
        "label": "Kimi（月之暗面）",
        "atlas_provider": "kimi-coding",
        "api_mode": "openai",
        # hermes kimi-coding profile 默认 api.moonshot.ai（海外）；国内主站 api.moonshot.cn（hermes 另有
        # kimi-coding-cn profile 同端点）。Atlas 传 base_url 覆盖 profile 默认。
        "default_base_url": "https://api.moonshot.cn/v1",
        "docs_url": "https://platform.kimi.com/docs/api/overview",
        # 思考参数：extra_body.thinking {type: enabled|disabled} 与 reasoning_effort 互斥（同发 400），
        # K3 系档位 low/high/max（medium→high、xhigh→max，见 reasoning_effort.KIMI_K3_OVERRIDES）。
        "notes": "thinking 开关与 reasoning_effort 二选一；K3 档位 low/high/max。查证 2026-10-02。",
    },
    {
        "id": "zai",
        "label": "智谱 GLM",
        "atlas_provider": "zai",
        "api_mode": "openai",
        # hermes zai profile 默认 api.z.ai（海外）；国内主站 open.bigmodel.cn（base_url 覆盖 profile 默认）。
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "docs_url": "https://docs.bigmodel.cn/cn/guide/start/concept-param",
        # 思考参数：extra_body.thinking {type: enabled|disabled}（GLM-4.5+）；GLM-5.3 起
        # reasoning_effort 支持 low/medium/high/max 分档（见 reasoning_effort.GLM53_EFFORTS）。
        "notes": "thinking.type 开关 + reasoning_effort（GLM-5.3 分档 low/medium/high/max）。查证 2026-10-02。",
    },
    {
        "id": "minimax",
        "label": "MiniMax",
        "atlas_provider": "minimax",
        "api_mode": "anthropic_messages",
        # hermes minimax profile 默认 api.minimax.io（海外）；国内主站 api.minimaxi.com
        # （hermes minimax-cn profile 同端点）。Atlas 传 base_url 覆盖 profile 默认。
        "default_base_url": "https://api.minimaxi.com/anthropic",
        "docs_url": "https://platform.minimaxi.com/docs/guides/quickstart",
        # 端点核实（2026-10-02）：国内 Anthropic 兼容 https://api.minimaxi.com/anthropic，
        # OpenAI 兼容 https://api.minimaxi.com/v1；Atlas 走 Anthropic 原生协议（hermes profile 同）。
        "notes": "国内 Anthropic 端点 /anthropic；思考走 Anthropic thinking 块。查证 2026-10-02。",
    },
    {
        "id": "stepfun",
        "label": "阶跃星辰 StepFun",
        "atlas_provider": "stepfun",
        "api_mode": "openai",
        # hermes stepfun profile 默认 api.stepfun.ai/step_plan/v1（Step Plan 订阅端点）；
        # 国内按量付费主站 api.stepfun.com/v1，Atlas 默认走主站、base_url 覆盖 profile 默认。
        "default_base_url": "https://api.stepfun.com/v1",
        "docs_url": "https://platform.stepfun.com/docs/zh/guides/developer/openai",
        # 端点核实（2026-10-02）：按量付费 https://api.stepfun.com/v1；Step Plan 订阅为
        # https://api.stepfun.com/step_plan/v1（在服务商 base_url 里手动改即可）。
        "notes": "主站 /v1 按量计费；Step Plan 订阅改用 /step_plan/v1。查证 2026-10-02。",
    },
    {
        "id": "xiaomi",
        "label": "小米 MiMo",
        "atlas_provider": "xiaomi",
        "api_mode": "openai",
        "default_base_url": "https://api.xiaomimimo.com/v1",
        "docs_url": "https://mimo.mi.com/docs/zh-CN/quick-start/summary/first-api-call",
        # 端点核实（2026-10-02）：OpenAI 兼容 https://api.xiaomimimo.com/v1，
        # Anthropic 兼容 https://api.xiaomimimo.com/anthropic（Atlas 走 OpenAI 兼容，与 hermes profile 一致）。
        "notes": "OpenAI 兼容 /v1；Bearer 鉴权。查证 2026-10-02。",
    },
    {
        "id": "siliconflow",
        "label": "硅基流动 SiliconFlow",
        "atlas_provider": "siliconflow",
        "api_mode": "openai",
        "default_base_url": "https://api.siliconflow.cn/v1",
        "docs_url": "https://api-docs.siliconflow.cn/docs/userguide/quickstart",
        # 端点核实（2026-10-02）：国内 https://api.siliconflow.cn/v1（海外 api.siliconflow.com/v1）。
        # hermes 无 profile → 通用 openai-compat 路径。思考参数：Qwen3 等思考模型
        # extra_body.enable_thinking / thinking_budget。models.dev 对应条目 "siliconflow-cn"。
        "notes": "国内站 /v1；enable_thinking / thinking_budget。查证 2026-10-02。",
    },
    {
        "id": "volcengine-ark",
        "label": "火山方舟（豆包）",
        "atlas_provider": "volcengine-ark",
        "api_mode": "openai",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "docs_url": "https://www.volcengine.com/docs/82379/1330310",
        # 端点核实（2026-10-02）：OpenAI 兼容 https://ark.cn-beijing.volces.com/api/v3。
        # hermes 无 profile → 通用 openai-compat 路径。思考参数：extra_body.thinking
        # {type: enabled|disabled}（豆包 seed 系）。models.dev 对应条目 "volcengine"。
        "notes": "OpenAI 兼容 /api/v3；thinking.type 开关。查证 2026-10-02。",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "atlas_provider": "openrouter",
        "api_mode": "openai",
        "default_base_url": "https://openrouter.ai/api/v1",
        "docs_url": "https://openrouter.ai/docs",
        # 思考参数：reasoning: {effort| max_tokens, exclude}（chat completions）。
        "notes": "统一聚合网关；reasoning.effort / reasoning.max_tokens。查证 2026-10-02。",
    },
    {
        "id": "ollama",
        "label": "Ollama（本地）",
        "atlas_provider": "ollama",
        "api_mode": "openai",
        "default_base_url": "http://127.0.0.1:11434/v1",
        "docs_url": "https://docs.ollama.com/api",
        # hermes 无独立 ollama profile："ollama" 是 custom profile 的别名（识别 11434 端口/
        # ollama 主机名走本地特殊逻辑）。思考参数：本地模型以 reasoning 输出为主，无统一开关。
        "notes": "本地 11434 的 OpenAI 兼容端点；hermes 经 custom profile 别名接入。查证 2026-10-02。",
    },
    {
        "id": "lmstudio",
        "label": "LM Studio（本地）",
        "atlas_provider": "lmstudio",
        "api_mode": "openai",
        "default_base_url": "http://127.0.0.1:1234/v1",
        "docs_url": "https://lmstudio.ai/docs/app/api",
        # hermes 对 provider=="lmstudio" 有专属路径（agent_init.py 按 provider 名识别，
        # 管理模型加载 explicit/jit）。默认端口 1234。
        "notes": "本地 1234 的 OpenAI 兼容端点；hermes 识别 provider==\"lmstudio\" 特殊路径。查证 2026-10-02。",
    },
    {
        "id": "custom",
        "label": "自定义端点",
        "atlas_provider": "custom",
        "api_mode": "openai",
        "default_base_url": "",
        "docs_url": "",
        # hermes custom profile：base_url 由用户配置；自动识别 ollama / groq 等端点形态。
        # 无官方文档链接（用户自填 OpenAI 兼容端点）。
        "notes": "任意 OpenAI 兼容端点，base_url 必填；密钥与服务商配置同普通服务商。查证 2026-10-02。",
    },
]

_PROVIDER_INDEX: dict[str, dict] = {entry["id"]: entry for entry in PROVIDERS}


# ---------------------------------------------------------------------------
# 离线模型回退行（M1，2026-10-03 补）
# ---------------------------------------------------------------------------
# models.dev 不可达/尚未收录时的离线兜底：Claude Code 2.1.257–2.1.284 的三个新默认
# 旗舰（docs/research/2026-10-03-mega-latest/02-claude-code.md，价格/上下文已核实）：
# - claude-sonnet-5-5：1M 上下文，$2/$10 每百万 token，cache 读 $0.20（v2.1.284）
# - claude-opus-5-5：1M 上下文，$4/$20 每百万 token（v2.1.280）
# - claude-fable-5-1：1M 上下文，$10/$50 每百万 token（v2.1.257）
# 行形状与 models_dev._BUILTIN_MODEL_METADATA 完全一致（models.dev 原始条目形状），
# 由 models_dev._builtin_model_metadata 在内建表未命中时读取；只补元数据，不进
# 模型选择器目录（在线时 models.dev 自动覆盖，行为不变）。未核实的字段（如 output
# 上限、cache_write 价）刻意缺席，消费方按未知处理而不是拿到臆造值。
CLAUDE_DEFAULT_MODEL_FALLBACKS: dict[tuple[str, str], dict] = {
    ("anthropic", "claude-sonnet-5-5"): {
        "limit": {"context": 1_000_000},
        "cost": {"input": 2.0, "output": 10.0, "cache_read": 0.2},
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "tool_call": True,
        "reasoning": True,
        "family": "claude-sonnet-5-5",
    },
    ("anthropic", "claude-opus-5-5"): {
        "limit": {"context": 1_000_000},
        "cost": {"input": 4.0, "output": 20.0},
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "tool_call": True,
        "reasoning": True,
        "family": "claude-opus-5-5",
    },
    ("anthropic", "claude-fable-5-1"): {
        "limit": {"context": 1_000_000},
        "cost": {"input": 10.0, "output": 50.0},
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "tool_call": True,
        "reasoning": True,
        "family": "claude-fable-5-1",
    },
}


def get_provider(pid: str) -> dict | None:
    """按 catalog id 取服务商条目（浅拷贝，防止调用方误改常量表），未知返回 None。"""
    entry = _PROVIDER_INDEX.get(str(pid or "").strip())
    return dict(entry) if entry is not None else None


def api_mode_for(pid: str) -> str:
    """服务商的 wire 模式（"openai" | "anthropic_messages"）；未知 id 兜底 "openai"。"""
    entry = _PROVIDER_INDEX.get(str(pid or "").strip())
    return str(entry["api_mode"]) if entry is not None else "openai"


def resolve_catalog_id(value: str) -> str | None:
    """catalog id 与 hermes provider id 双向归一到 catalog id。

    settings 的 providers.<pid> 密钥/配置一律按 catalog id 存储；模型条目的
    atlas_provider 字段存的是 hermes id（如 qwen→alibaba、kimi→kimi-coding）。
    """
    v = str(value or "").strip()
    if not v:
        return None
    if v in _PROVIDER_INDEX:
        return v
    for entry in PROVIDERS:
        if entry["atlas_provider"] == v:
            return str(entry["id"])
    return None
