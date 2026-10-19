# 未解与盲点（UNKNOWNS）

如实记录，不用猜测填充。

---

## U1 — `codex.exe` 函数级未反编译

- **对象**：`app/resources/codex.exe`，341,312,816 字节，Rust，符号已 strip。
- **已做**：提取 1,413,792 条字符串、1,850 条协议关键词；PE 节表（`.text` 262 MB、`.rdata` 65.9 MB、`.pdata` 11.8 MB）；确认与 CLI 0.163.0 同源。
- **未做**：函数边界识别、伪代码、交叉引用、调用图。
- **原因**：REA 对该体量报 `provider_timeout`（330 s 超时）；Ghidra 单次分析预计需数小时至数十小时且需大量内存。
- **解锁需要**：把 codex.exe 按 `.text` 偏移分段（如每 20 MB）分批送 Ghidra/REA，或用 `codex-commands` 的调试符号（未公开）。
- **影响**：无法确认是否有字符串未覆盖到的隐藏逻辑。

## U2 — 74 个匿名 Statsig gate 用途未知

- **已知**：`1079089693`、`3520348126`、`3097567806`、`224248639`、`463790362`、`2031707412`、`3371896889` 等 74 个数字 ID，调用点在 `app-initial-*.js`。
- **未知**：每个 gate 控制什么功能。
- **原因**：Statsig 的匿名 gate 名称不下发到客户端，只下发 hash ID；映射在服务端。
- **解锁需要**：拿到服务端 Statsig 配置（不可得），或对照不同账号的实际表现做差分（需要多个账号）。
- **影响**：无法给出"哪些功能被远程关闭"的完整清单。

## U3 — 服务端实现完全不可得

| 服务端 | 已知客户端接口 | 服务端实现 |
|---|---|---|
| 模型网关（Responses API） | 请求结构在 `core/src/client.rs` | U |
| Statsig 配置 | gate ID | U |
| Marketplace 服务 | `marketplace/*` RPC | U |
| Remote Control 配对服务 | `remoteControl/pairing/*` | U |
| Realtime WebRTC 服务 | `thread/realtime/*` | U |
| 账号/计费 | `account/*` RPC | U |
| 远程压缩 V2 | `RemoteCompactionSupport::V2` | U |

## U4 — 未做端到端验证的链路

| 链路 | 阻塞原因 |
|---|---|
| 完整对话（模型调用） | 需要可用额度；本机 CODEX_HOME 磁盘不足（doctor 报 <1 GiB） |
| 工具调用往返 | 同上 |
| 子代理派生与 mailbox | 同上 |
| 压缩实际触发 | 同上（需要长对话） |
| Remote Control | 需要两台设备 + 账号 |
| Realtime 语音 | 需要 WebRTC 服务 + 麦克风权限 |
| Agent Jobs 批处理 | 需要额度 + CSV 数据 |
| Plugin Marketplace 安装 | 需要登录 + 市场服务 |
| Windows 沙箱完整 ACL | 需要提权与管理账号 |

## U5 — 登录后界面无截图

- **原因**：已安装实例包含真实邮箱、会话标题、项目名；不使用它截图。
- **替代**：通过 2,176 个前端 chunk 的文件名/组件符号/协议方法推断界面结构（见 `UI-GALLERY.md` 定位表）。
- **影响**：无法验证"界面元素与源码的像素级对应"，也无法发现纯 UI 层的隐藏交互（如特定手势、快捷键组合）。

## U6 — 函数枚举不完整

- **已知**：全仓库 59,107 个 `fn` 声明（grep 计数）；266 个关键符号已建索引。
- **未做**：完整 AST 级枚举（需要 `cargo doc`/`rust-analyzer` 或 tree-sitter 全量解析）。
- **原因**：155 个 crate 全量解析耗时且需要依赖下载（本机磁盘不足）。
- **影响**：`FUNCTION-CATALOG.md` 只覆盖核心路径，不是全量符号表。

## U7 — MCP / Skills / Hooks / Guardian 未逐函数精读

- **已知**：协议方法、crate 存在、表结构。
- **未知**：具体实现细节（如 hook 的执行顺序保证、Guardian 的风险评分算法、MCP 工具 schema 压缩策略）。
- **解锁需要**：精读 `codex-mcp`、`rmcp-client`、`hooks`、`ext/guardian-v2` 四个 crate。

## U8 — Chromium / Electron 框架层未分析

- **范围**：`chrome.dll`、`icudtl.dat`、`*.pak`、`v8_context_snapshot.bin` 等约 1.4 GB。
- **判断**：不属于 Codex 产品逻辑，属于 Electron 42.3.0 运行时。
- **影响**：若存在 Chromium 层 0-day 或定制补丁，本报告不覆盖。

## U9 — 模型系统提示只拿到片段

- **已知**：`codex debug models` 输出中，每个模型的 `model_messages` 含 `persistent_instructions`（实测抓到 GPT-6-Astra 的持久模式提示全文）。
- **未知**：完整的 base instructions、工具使用指引、以及服务端实际注入的最终提示。
- **原因**：最终提示由服务端拼装，客户端只有模板。

## U10 — 版本漂移风险

- 研究基于 `rust-v0.163.0` / Desktop `26.1013.4894.0`（2026-10-19 核对为最新稳定版）。
- 上游已有 `rust-v0.164.0-alpha.1~4`；若转正，本报告的行号与协议方法可能变化。
- **建议**：复现前先跑 `codex --version` 与 `codex features list` 对比。
