# R5 — Hermes 渠道 platform adapters 移植可行性研究

> 来源冻结：Hermes fork `D:\hermes-agent`（branch `atlas`，HEAD `ef4571dec5`，= upstream `c8301ea6c9` + merge）。
> Atlas 本体：`D:\Atlas` @ `a034bff`。本 lane 只读研究，不改代码。
> 结论先行：**直接整目录搬不可行**（公共基类 `gateway/platforms/base.py` 4934 行，拖着 multiplex profile / delivery ledger / exec-approval / TTS / i18n 一整套）；**但 adapter 与 agent 的接口天然是回调注入式，协议层代码可整体借用的比例很高**。建议 Atlas 定义一个薄 `ChannelAdapter` ABC，五个渠道按"抄协议层 + 薄适配层"落地，Telegram 先用现有 raw-httpx 版收编进新框架。

---

## 1. adapter 公共契约

### 1.1 基类与生命周期

- 基类：`BasePlatformAdapter(ABC)`，`D:\hermes-agent\gateway\platforms\base.py:1918`（该文件共 4934 行，含 SendResult/媒体缓存/发送重试/typing 等全部公共件）。
- 构造：`__init__(self, config: PlatformConfig, platform: Platform)`（base.py:1967）。`config` 来自 `gateway/config.py:410` 的 `PlatformConfig`（enabled/token/api_key/home_channel/extra dict/channel_overrides）；`platform` 是 `gateway/config.py:217` 的 `Platform` 枚举。
- **抽象方法只有 4 个**（签名级）：

```python
@abstractmethod
async def connect(self, *, is_reconnect: bool = False) -> bool      # base.py:2726
@abstractmethod
async def disconnect(self) -> None                                   # base.py:2732
@abstractmethod
async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> SendResult   # base.py:2736
@abstractmethod
async def get_chat_info(self, chat_id: str) -> Dict[str, Any]        # base.py:4858
                      # 返回至少 {"name": ..., "type": "dm"|"group"|"channel"}
```

- 生命周期由 runner 驱动：`GatewayRunner._create_adapter()`（`gateway/run.py`，先查 `platform_registry.create_adapter(name, config)`）→ `_wire_adapter_handlers()`（`gateway/run_adapters.py:1277`）注入全部回调 → `connect()` → 收发 → `disconnect()`。重连由 runner 的 watcher 负责（adapter 内部也有 SDK 级断线重连/熔断，如 telegram 的 polling-stall 检测、dingtalk 的 circuit breaker）。
- 可选覆盖方法（base 提供默认实现，adapter 按能力覆盖）：`send_typing` / `stop_typing`、`send_image` / `send_image_file` / `send_document` / `send_voice` / `send_video` / `send_animation`、`edit_message` / `delete_message`、`send_clarify` / `send_slash_confirm` / `send_exec_approval`（按钮审批，回调 id 约定 `cl:/appr:/sc:`）、`format_message`（markdown→平台格式）、`truncate_message`、`build_source(...)`（构造 `SessionSource`，禁止直接 new）、`set_status_text`。
- 类级能力开关（布尔类属性）：`supports_code_blocks`、`supports_status_text`、`supports_async_delivery`、`splits_long_messages`、`typed_command_prefix`、`interactive_resume`、`max_message_length`（registry 侧）、`REQUIRES_EDIT_FINALIZE`（钉钉 AI 卡片）。

### 1.2 消息归一化形状

`gateway/platforms/event.py`（144 行，叶子模块）：

- `MessageType(Enum)`：`TEXT/LOCATION/PHOTO/VIDEO/AUDIO/VOICE/DOCUMENT/STICKER/COMMAND`（event.py:24）。
- `MessageEvent`（dataclass，event.py:45）核心字段：`text`、`message_type`、`user_id/user_name`、`source: SessionSource`、`message_id`、`media_urls/media_types`（本地文件路径）、`reply_to_message_id/reply_to_text/reply_to_author_*`、`prompt_response`（按钮审批回填）、`auto_skill`、`channel_prompt`、`internal`（旁路授权）、`metadata: dict`、`timestamp`、`allow_gateway_control`、`reply_expected`；方法 `is_command()/get_command()/get_command_args()`。
- `ProcessingOutcome(Enum)`：SUCCESS/FAILURE/CANCELLED（hook 分类用）。
- `SessionSource`（`gateway/session.py:66`）：`platform, chat_id, chat_name, chat_type("dm"|"group"|"channel"|"thread"), user_id, user_name, thread_id, scope_id, parent_chat_id, message_id, profile, ...` — 回复路由 + 会话 key 的统一身份。

### 1.3 回复路径（adapter ↔ agent 的全部接触面）

adapter **从不 import agent/LLM 代码**。完整闭环：

1. adapter 收到平台事件 → 归一化为 `MessageEvent` → `self.build_source(...)` 盖上 transport 身份 → `self.handle_message(event)`（base.py:4039；内部做会话去重/排队/忙时分流）。
2. base 持有的 `self._message_handler`（`MessageHandler = Callable[[MessageEvent], Awaitable[Optional[str|EphemeralReply]]]`，base.py:1859）由 runner 通过 `adapter.set_message_handler(...)` 注入（run_adapters.py:1288）；同场注入的还有 `set_busy_session_handler`、`set_authorization_check`、`set_reaction_handler`、`set_topic_recovery_fn`、`set_fatal_error_handler`、`set_session_store`。
3. runner 跑完 agent 后，用 `adapter.send(chat_id, content, reply_to=..., metadata=...)` 把回复发回渠道（`gateway/run.py:766`）；流式草稿走 `adapter.send_draft / send_or_update_status`。

**这层已经是"宿主提供回调/接口"的形状** — 移植时只需把 `_message_handler` 换成 Atlas 的 agent 入口回调。

### 1.4 插件注册机制

- 打包形态：`plugins/platforms/<name>/`，`plugin.yaml`（kind: platform + requires_env/optional_env 富清单）+ `adapter.py` + `register(ctx)` 入口。
- 加载：`plugins/plugin_loader.py`（185 行，按路径 import 包并执行 `register(ctx)`）；`PluginContext.register_platform(name, label, adapter_factory, check_fn, ...)`（`hermes_cli/plugins.py:808`）把 `PlatformEntry` 写进 `gateway/platform_registry.py:41` 的进程级注册表（406 行；支持 deferred 懒加载、per-profile scope、被动探测 `check_fn` 与主动装依赖 `ensure_deps_fn` 分离）。
- `PlatformEntry` 关键字段：`adapter_factory`、`check_fn`（依赖可导入？）、`ensure_deps_fn`（lazy pip 安装）、`validate_config`、`is_connected`、`required_env`、`allowed_users_env/allow_all_env`（授权 env 名）、`cron_deliver_env_var`（`*_HOME_CHANNEL`）、`standalone_sender_fn`（网关不在场时的进程外投递）、`max_message_length`、`env_enablement_fn`/`apply_yaml_config_fn`（env/YAML→extra 桥）。
- 每个渠道一个 `register(ctx)`（telegram adapter.py:7404、slack:6897、feishu:4482、dingtalk:849、wecom:837——wecom 一次注册两个平台 `wecom` + `wecom_callback`）。

### 1.5 文件清单与行数（五渠道 + 可搬运纯件）

| 渠道 | 文件（`plugins/platforms/<name>/`） | 行数 |
|---|---|---|
| telegram | `adapter.py` | 7411 |
| | `update_admission.py`（PTB Application 子类，update 准入/防卡死） | 248 |
| | `telegram_network.py`（httpx 直连 IP 兜底 transport） | 305 |
| | `inline_picker.py` / `telegram_context.py` / `telegram_entities.py` / `telegram_ids.py` | 98 / 53 / 68 / 31 |
| | `plugin.yaml` | 39 |
| slack | `adapter.py` | 6925 |
| | `block_kit.py`（**纯 stdlib**，Block Kit 渲染/消毒，可直接搬） | 621 |
| | `plugin.yaml` | 45 |
| feishu | `adapter.py` | 4494 |
| | `feishu_comment.py` / `feishu_comment_rules.py`（云文档评论触发，lark-oapi） | 638 / 288 |
| | `feishu_meeting_invite.py` / `feishu_admission_diagnostics.py` | 141 / 36 |
| | `plugin.yaml` | 44 |
| dingtalk | `adapter.py` | 858 |
| | `inbound.py`（文本/媒体提取，**仅 1 行依赖** `gateway.platforms.event`） | 171 |
| | `plugin.yaml` | 39 |
| wecom | `adapter.py` | 852 |
| | `callback_adapter.py`（自建应用 HTTP 回调） | 315 |
| | `streaming.py`（WS 流式回复队列） | 370 |
| | `media.py` / `send_queue.py` / `wecom_crypto.py`（**纯 stdlib+cryptography**，腾讯 WXBizMsgCrypt 兼容实现，可直接搬） | 358 / 82 / 114 |
| | `plugin.yaml` | 52 |

参考实现（Email/Webhook）：

- Email：`plugins/platforms/email/adapter.py` 936 行 — **纯 stdlib**（imaplib 轮询 + smtplib 发送），轮询间隔 `EMAIL_POLL_INTERVAL` 默认 15s，凭据 `EMAIL_ADDRESS/EMAIL_PASSWORD`。
- Webhook：内置 `gateway/platforms/webhook.py` 965 行 — aiohttp server，按 route 的 HMAC secret 验签（V2 带时间戳防重放），per-route prompt 模板 + rate limit + 幂等缓存。

公共框架件（Atlas 若走"搬基类"路线必须一起扛）：

| 文件 | 行数 | 内容 |
|---|---|---|
| `gateway/platforms/base.py` | 4934 | BasePlatformAdapter、SendResult、ExecApprovalPrompt、媒体缓存、`_send_with_retry`、`classify_send_error` |
| `gateway/platforms/helpers.py` | 680 | MessageDeduplicator、compile_mention_patterns、bounded_put、send_chunks |
| `gateway/platforms/_shared.py` | 250 | `get_scoped_secret`（**耦合 agent.secret_scope**）、extra_or_secret、apply_yaml_bridge、env_is_connected、send_error |
| `gateway/platforms/event.py` | 144 | MessageEvent/MessageType |
| `gateway/platform_registry.py` | 406 | PlatformEntry + 注册表 |
| `gateway/session.py` | ~ | SessionSource（耦合 `Platform` 枚举） |
| `gateway/pairing.py` + `authz_mixin.py` | ~ | `*_ALLOWED_USERS` 授权门 |

---

## 2. 依赖清单（pyproject.toml extras，Python `>=3.11,<3.15`）

| 渠道 | 第三方包（hermes 锁定版本） | Atlas 现状 |
|---|---|---|
| telegram | `python-telegram-bot[webhooks]==22.8`（extras `telegram`，pyproject:334）；httpx（已在核心依赖，:53 `httpx[socks]==0.28.1`） | Atlas 现版零 SDK（raw httpx）；引 PTB 是新增重依赖 |
| slack | `slack-bolt==1.30.0` + `slack-sdk==3.44.1` + `aiohttp==3.14.3`（:276） | 全新增 |
| feishu | `lark-oapi==1.6.8` + `qrcode==7.4.2`（:471）；webhook 模式另需 `aiohttp`（SDK 之外独立导入，adapter.py:47-53） | 全新增 |
| dingtalk | `dingtalk-stream==0.24.3` + `httpx`（install_hint 见 adapter.py:851） | 全新增（httpx 已有） |
| wecom | `aiohttp`（WS/回调 server）+ `httpx`（API 调用）+ `cryptography`（回调 AES）；extras `wecom = ["defusedxml==0.7.1"]`（:297）；`wecom_crypto.py` 只依赖 stdlib+cryptography，自包含 | cryptography 视 Atlas 现有依赖 |
| email | 无（stdlib imaplib/smtplib） | 零新增 |
| webhook | aiohttp（或复用 Atlas 现有 web 框架路由） | 视实现 |

注意：hermes 把这些 SDK 全部做成**可选 extras + 懒加载**（adapter 顶部 `try: import ... except ImportError: XXX_AVAILABLE=False`），`check_fn` 被动探测、`ensure_deps_fn` 在 connect 前才 `pm.sync_venv` 安装。Atlas 应沿用"缺依赖只降级该渠道，不拖垮本体"的模式（与 Atlas 现有 C6 注册降级纪律一致）。

---

## 3. adapter 与 agent 的耦合点（复制 vs 适配层的判据）

### 3.1 对 hermes 内部模块的 import（逐渠道）

公共五件套（每个 adapter 都有）：`gateway.config`（Platform, PlatformConfig）、`gateway.platforms.base`（BasePlatformAdapter, SendResult, ExecApprovalPrompt, 媒体缓存…）、`gateway.platforms.event`、`gateway.platforms._shared`（get_scoped_secret 等）、`agent.i18n.t`（中文/英文文案）。

- **telegram**：额外 `hermes_cli.setup_platforms`（交互式 setup）、`agent.deadline.run_bounded_async`、`gateway.authz_mixin._coerce_allow_set`、`gateway.platforms.helpers`、`utils`（env_int/env_float）。
- **slack**：`agent.compression_marker`、`agent.retry_utils`、`agent.secret_scope`、`hermes_cli.version_info`（User-Agent）。
- **feishu**：`pm.install_hint`、`gateway.status`（scoped lock）、`hermes_constants.get_hermes_home`、`utils.atomic_json_write`。
- **dingtalk**：`gateway.platforms.helpers`（MessageDeduplicator, compile_mention_patterns）。
- **wecom**：`pm.install_hint`、`gateway.platforms.helpers`（bounded_put, send_chunks）、`gateway.platforms.access_policy_mixin.OwnAccessPolicyMixin`；`_standalone_send` 还摸 `tools.send_message_senders._live_adapter`（进程外 cron 投递时复用活 adapter）。

### 3.2 判定

- 与 **agent 执行环**的耦合：**零**。消息进 `handle_message`（回调），回复出 `send()`（被调）。§1.3 已证。→ "Atlas 提供回调/接口"完全成立。
- 与 **hermes 框架**的耦合：重。base.py 的 `handle_message`/`build_source`/`truncate_message`/`_is_sender_authorized`/typing/retry 是所有 adapter 的地基层；`_shared.get_scoped_secret` 背后是 profile secret scope。五个 adapter 对 base 方法的实际调用量并不大（`self.build_source` 1–5 次、`handle_message` 1–9 次、`format_message`/`truncate_message` 各若干——见研究过程实测），**每个 adapter 的主体是 SDK/协议代码，不是框架代码**。
- 结论：整文件复制必须连 base.py+event+session+config+_shared+helpers（~6400 行）一起搬，且这些件互相咬合 multiplex profile/ledger/TTS/i18n——**不建议**。建议：Atlas 自定薄 ABC（下文 §6），协议层逐文件搬运（搬运友好清单：`block_kit.py` 621 行纯 stdlib、`wecom_crypto.py` 114 行纯 stdlib+cryptography、`telegram_ids.py`/`telegram_entities.py`/`telegram_context.py` 纯 stdlib、`dingtalk/inbound.py` 改 1 行 import、`wecom/send_queue.py`+`streaming.py` 基本纯 asyncio）。

---

## 4. 飞书 / 钉钉 / 企业微信 的接收模式与凭据

| 渠道 | 接收模式 | 细节 | 凭据（plugin.yaml requires_env） |
|---|---|---|---|
| feishu | **WebSocket（默认）或 HTTP webhook（可选）** | WS：`FEISHU_CONNECTION_MODE=websocket`（默认），`lark_oapi.ws.Client` 长连接，事件经 `EventDispatcherHandler` 分发；webhook：`FEISHU_CONNECTION_MODE=webhook` 时自起 aiohttp server（默认 path `/feishu/webhook`，端口 `FEISHU_WEBHOOK_PORT`），**必须**配 `FEISHU_VERIFICATION_TOKEN` 或 `FEISHU_ENCRYPT_KEY`（adapter.py:1505），验签+解密。域切换 `FEISHU_DOMAIN=feishu|lark`（国内/国际） | `FEISHU_APP_ID` + `FEISHU_APP_SECRET`（必填）；`FEISHU_ALLOWED_USERS`、`FEISHU_HOME_CHANNEL`（可选） |
| dingtalk | **Stream Mode（WebSocket）** | `dingtalk_stream.DingTalkStreamClient(Credential(client_id, client_secret))` + `register_callback_handler(ChatbotMessage.TOPIC, _IncomingHandler)`；SDK 自带重试，adapter 外层加 5 次熔断（`RECONNECT_CIRCUIT_BREAKER_TRIPS`）。出向另支持静态机器人 `DINGTALK_WEBHOOK_URL`（cron 投递） | `DINGTALK_CLIENT_ID` + `DINGTALK_CLIENT_SECRET`；`DINGTALK_ALLOWED_USERS`、`DINGTALK_HOME_CHANNEL` |
| wecom | **两套并存**：① `wecom`（智能机器人）：**raw WebSocket**（aiohttp `ws_connect` 到 `WECOM_WEBSOCKET_URL`，心跳、`aibot_respond_msg` 流式回复队列，同一 bot 仅允许一条 WS，第二条会把第一条踢下线）；② `wecom_callback`（自建应用）：**HTTP 回调**（aiohttp server，GET URL 验证 + POST AES 加密 XML，`WXBizMsgCrypt` 即时 ack、解密后排队给 agent） | ① `WECOM_BOT_ID` + `WECOM_SECRET`；② `WECOM_CALLBACK_CORP_ID` + `WECOM_CALLBACK_CORP_SECRET` + `WECOM_CALLBACK_AGENT_ID` + `WECOM_CALLBACK_TOKEN` + `WECOM_CALLBACK_ENCODING_AES_KEY`；均有 `*_ALLOWED_USERS`/`*_HOME_CHANNEL` |

凭据管理方式（hermes 侧）：全部走**环境变量**（`plugin.yaml` 声明 `password: true` 的进 secret 提示），读取一律经 `_shared.get_scoped_secret` → `agent.secret_scope`（profile 作用域，缺省回落 `os.environ`；绝不裸 `os.getenv`，多 profile 下防串号）。**hermes 不用 keyring** —— Atlas 落地时把"env 读取"换成 KeyringCredentialStore 即可，adapter 代码里只需替换这一个读取函数。

---

## 5. Atlas 现有 `core/atlas/telegram.py` 与 Hermes telegram adapter 的关系

现状（`D:\Atlas\core\atlas\telegram.py`，263 行）：

- **轮询式 outbound+轻 inbound 通道**：raw `httpx` 直打 Bot API（`getUpdates` 长轮询 25s / `sendMessage` / `answerCallbackQuery`），内联键盘审批（`request_approval` 返回 Future），`submit_task`/`command_handler` 回调注入，`allowed_user_ids` 白名单，设置存 `telegram.json`，token 存 `KeyringCredentialStore`（keyring service `"Atlas"`，key `atlas.telegram.bot_token`）。
- 被 `core/atlas/server.py:815` 与 `core/atlas/runtime/hub.py:250` 各自实例化；`KeyringCredentialStore` 还被 `core/atlas/models/credentials.py:340`、`models/__init__.py:234` 复用（模型密钥也走它）。测试在 `core/tests/test_backend_parity_wave5.py`。

与 Hermes telegram adapter（7411 行 PTB）的关系：**同渠道不同物种**。Hermes 版多了 threads/topics、流式编辑、原生媒体收发、inline picker、群 @ 门控、webhook 模式、直连 IP 兜底 transport、update 准入防卡死——但它压在 PTB 22.8 + base.py 4934 行之上。

判定：

- **不能用 Hermes 版直接替换**。替换=引入 PTB+框架件，违背 Atlas"渠道缺依赖只降级、本体轻依赖"的纪律；且现有 TelegramService 的审批 Future/submit_task 语义与 server.py/hub.py 强绑定。
- **可以吸收**：把现有 TelegramService 收编为 `channels/telegram/` 的 `ChannelAdapter` 实现（协议代码原样保留：httpx 轮询、审批键盘），在其上补 Hermes 已验证的语义——`update_id` 持久化防重放（现版 `_offset` 在内存，重启重放）、`allowed_updates` 增量、`_is_sender_authorized` 型白名单统一化、`SendResult{success,message_id,error_kind}` 返回值、typing 指示。`telegram_ids.py`/`telegram_entities.py`/`telegram_network.py`（直连 IP 兜底）可作后续增强直接搬运。
- `KeyringCredentialStore` 应上移为渠道/凭据公共件（§6.3），`atlas.telegram` 保留 re-export 以免破坏 `models/credentials.py` 与测试。

---

## 6. Atlas 落点建议

### 6.1 Channel plugin contract（ABC 签名级，取 hermes 契约的 Atlas 子集）

```python
# core/atlas/channels/base.py
@dataclass(slots=True)
class SendResult:
    success: bool
    message_id: str | None = None
    error: str | None = None
    error_kind: str | None = None      # too_long|forbidden|not_found|rate_limited|transient|unknown
    retryable: bool = False

@dataclass(slots=True)
class ChannelMessage:                  # hermes MessageEvent 的 Atlas 子集
    channel: str                       # "telegram"
    chat_id: str
    user_id: str | None = None
    user_name: str | None = None
    chat_type: str = "dm"              # dm|group|channel|thread
    thread_id: str | None = None
    text: str = ""
    message_type: str = "text"         # text|photo|voice|document|command
    message_id: str | None = None
    media_paths: list[str] = field(default_factory=list)   # 已落盘本地路径
    reply_to_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

MessageHandler = Callable[[ChannelMessage], Awaitable[None]]   # Atlas 宿主注入；回复经 adapter.send 回流

class ChannelAdapter(ABC):
    name: ClassVar[str]                # "telegram"
    label: ClassVar[str]
    required_credentials: ClassVar[tuple[str, ...]] = ()       # keyring key 后缀，如 ("bot_token",)
    max_message_length: ClassVar[int] = 0
    interactive: ClassVar[bool] = True                          # webhook 类 False（auto-resume 语义，抄 hermes）

    def __init__(self, settings: Mapping[str, Any], credentials: CredentialStore,
                 on_message: MessageHandler) -> None: ...

    @abstractmethod
    async def start(self) -> bool          # = connect()；False 时必须设置 self.fatal_error
    @abstractmethod
    async def stop(self) -> None           # = disconnect()
    @abstractmethod
    async def send(self, chat_id: str, content: str, *, thread_id: str | None = None,
                   reply_to: str | None = None, metadata: Mapping[str, Any] | None = None) -> SendResult
    async def send_typing(self, chat_id: str) -> None: ...
    async def request_approval(self, chat_id: str, description: str) -> Future[bool]: ...   # 现有 telegram.py 语义推广
    def is_configured(self) -> bool        # 凭据在库？
    def is_available(self) -> bool         # 第三方 SDK 可导入？（被动探测，永不安装）

    # 宿主侧注册表
    # core/atlas/channels/registry.py：register(ChannelAdapter 子类) / create(name) / all()
    # 缺依赖只跳过该渠道并记 warning（对齐 server.py C6 降级纪律）
```

宿主（`runtime/hub.py` 或新的 `channels/host.py`）职责 = hermes runner 的极简版：装 `on_message` 回调 → 喂 agent orchestrator → `adapter.send()` 回流；去重/会话忙判定先放宿主，不上 ledger/multiplex。

### 6.2 七渠道实现策略

| 渠道 | 策略 | 说明 / 搬运清单 |
|---|---|---|
| Telegram | **适配层（现有代码收编）** | `core/atlas/telegram.py` 重构进 `channels/telegram/`：`TelegramChannel(ChannelAdapter)` 包住现 `TelegramService` 的 httpx 轮询/审批逻辑；搬 `telegram_ids.py`/`telegram_entities.py`（纯 stdlib）；`update_id` 持久化进 telegram.json；PTB 与 `telegram_network.py` 兜底作为后续增强，不进第一期 |
| Slack | **新写（抄 hermes 协议层）** | slack-bolt Socket Mode 骨架抄 `slack/adapter.py` 的 connect/handler 段；**整搬 `block_kit.py`（621 行纯 stdlib）**；凭据 `bot_token`+`app_token` 两把 |
| 飞书 | **新写（抄 hermes 协议层）** | lark-oapi WS 默认模式抄 `feishu/adapter.py` 的 WS 分发与 @门控；webhook 模式（aiohttp+verification_token/encrypt_key）二期；评论触发 `feishu_comment*` 不搬（Atlas 无对应场景则砍） |
| 钉钉 | **新写 + 小搬** | dingtalk-stream Client 骨架抄 `dingtalk/adapter.py`（全插件仅 1029 行，五渠道最小）；**搬 `inbound.py`（171 行，改 1 行 import）**；熔断抄 5 次断路器 |
| 企业微信 | **混合：搬 crypto + 新写传输** | **整搬 `wecom_crypto.py`（114 行，零 hermes 依赖）**；`send_queue.py` 近乎零依赖可搬；WS 机器人模式与回调模式二选一先做回调（HTTP 回调对 Atlas server 最自然，server 已有 web 服务），WS 智能机器人二期 |
| Email | **新写（照抄 hermes 思路，stdlib）** | `plugins/platforms/email/adapter.py`（936 行纯 stdlib imaplib 轮询+smtplib）作蓝本压缩实现；imaplib 无 IDLE，轮询 15–60s；凭据 address+password（app password） |
| Webhook | **新写（挂 Atlas 现有 server 路由）** | 不自起 aiohttp；在 `core/atlas/server.py` 加 `/channels/webhook/<name>` 路由：HMAC 验签（V2 带时间戳防重放，抄 `gateway/platforms/webhook.py:1-9` 的设计）、per-route secret、body 大小上限、幂等缓存。`interactive=False` |

### 6.3 建议文件树与凭据方案

```
core/atlas/channels/
  __init__.py            # load_channels(registry) + 渠道开关
  base.py                # ChannelAdapter / ChannelMessage / SendResult / MessageHandler
  registry.py            # 注册表 + create(name)：is_available() False → 降级 warning
  credentials.py         # KeyringCredentialStore 自 telegram.py 上移至此（service="Atlas"，
                         #   key "atlas.channel.<name>.<field>"，如 atlas.channel.telegram.bot_token）
  host.py                # 轻宿主：装 handler→agent→send 回流；忙判定/去重先放这里
  telegram/
    __init__.py channel.py approvals.py     # 现 telegram.py 收编；settings 仍 telegram.json
  slack/    __init__.py channel.py block_kit.py     # block_kit.py 整搬
  feishu/   __init__.py channel.py
  dingtalk/ __init__.py channel.py inbound.py       # inbound.py 整搬改 1 行
  wecom/    __init__.py channel.py callback.py crypto.py   # crypto.py 整搬
  email/    __init__.py channel.py
  webhook/  __init__.py channel.py routes.py        # 路由挂 server.py
```

- 凭据：沿用 `KeyringCredentialStore`（keyring，service `"Atlas"`）。现有 key `atlas.telegram.bot_token` 原名保留（`models/credentials.py` 与测试依赖）；新渠道统一 `atlas.channel.<name>.<field>` 命名空间。非密设置（enabled/allowed_users/home_chat_id/notify_on）继续走各渠道 JSON settings 文件（现 `telegram.json` 模式推广）。adapter 内读凭据统一走构造注入的 `CredentialStore`（对应 hermes 的 `get_scoped_secret` 单点替换位）。
- 迁移步序建议：① base/registry/credentials + telegram 收编（零新依赖，先立契约）→ ② webhook（server 路由，零新依赖）→ ③ email（stdlib）→ ④ dingtalk/wecom（小 SDK，代码量小）→ ⑤ feishu（lark-oapi）→ ⑥ slack（bolt+sdk+block kit，代码量最大）。
- 依赖纪律：每个渠道 SDK 独立 optional extra（`atlas[slack]` 等），`is_available()` 被动探测，永不自动 pip install（对齐 hermes check_fn/ensure_deps_fn 分离的教训，pyproject:59-72 注释里的"status 显示顺带 pip 安装"事故）。

### 6.4 风险与注意

- hermes 五 adapter 均为 `ef4571dec5` 冻结版，行数大（telegram 7.4k / slack 6.9k）源于 hermes 特有功能（multiplex profile、exec-approval 按钮、i18n、cron standalone sender）——**不要按文件整抄 adapter.py**，按"connect/receive/normalize/send 四段"摘协议代码。
- wecom WS"单 bot 单连接"约束（第二连接踢第一连接）意味着 Atlas 侧若有 hub+server 两个入口，必须共享同一 adapter 实例（现有 `TelegramService` 在 server.py 与 hub.py 双实例化的问题在 wecom/slack 上会成为正确性问题）。
- 钉钉/飞书回复接口有平台侧时效与 ack 语义（dingtalk AI 卡片 `REQUIRES_EDIT_FINALIZE`、wecom `aibot_respond_msg` ack 队列），agent 慢回复时需要"先 ack 占位、后编辑"路径——直接抄 hermes 对应段。
- Email 轮询 + webhook 类渠道 `interactive=False`（hermes 语义：auto-resume 提示语分叉，base.py:1949 注释 #57056），Atlas 宿主需要对应分支。
