# 变更通知：AI计划 对 Atlas 的配置改动（2026-09-26）

> 给 P8D worker（Codex）的交接说明。**改动目的：给 Atlas 接上真实的模型网关，让它能真正跑起来。**
> 以下改动与 P8D 的 Scope 不重叠，但有几处会影响你的打包/验收，请先读第 3 节。

---

## 1. 改了什么（文件清单）

| 文件 | 改动 | git 状态 | 是否影响打包产物 |
|---|---|---|---|
| `config/atlas.toml` | 网关从 `https://api.monkeyapi.net`（无 key）改为本地反重力网关 `http://127.0.0.1:8045/v1`；默认模型 `claude-sonnet-4` → `gemini-3.8-flash-high`；新增 `[[models.custom]]` 定义（`litellm_model = openai/gemini-3.8-flash-high`）；清理 `auto_start`（原来列了 `git`/`brave-search` 但这两个 server 段未定义） | **gitignored**（`.gitignore:19`） | ❌ 不进包（`extraResources` 只含 `atlas.example.toml`） |
| `data/user-settings.json` | 运行时由 settings API 写出（网关 + 选中模型） | **gitignored** | ❌ |
| `ecosystem.config.js` | 删掉 `env: { ATLAS_API_BASE: 'https://api.monkeyapi.net' }`（该环境变量优先级最高，用 PM2 启动会把网关强行拉回 monkeyapi）；改为 `http://127.0.0.1:8045/v1` + 占位 key | 已修改（入库） | ❌ PM2 配置，不影响 npm/electron-builder 流程 |
| `start-atlas.bat` | **新增**：一键启动后端（自动定位 Hermes venv 的 python） | 新增未跟踪 | ❌ |
| `.gitignore` | 新增 `frontend/release/` 和 `frontend/windows-release/` | 已修改（入库） | ❌ |
| `C:\Users\25011\AppData\Roaming\Atlas\config\atlas.toml` | **新增**：打包版（安装版）运行时配置，与开发版同网关 | 仓库外 | ❌ 不进包 |
| `config/atlas.toml.bak-20260926-024700` | 原 monkeyapi 版配置备份 | 未跟踪 | ❌ |

---

## 2. 为什么改（配置优先级 —— 最大的坑）

`core/atlas/config.py` 里网关配置有**三层覆盖关系**：

1. **环境变量** `ATLAS_API_BASE` / `ATLAS_API_KEY`（最高，压过一切）
2. **`<DATA_ROOT>/data/user-settings.json`**（settings API 写出后**永久覆盖** `atlas.toml`）
3. **`<DATA_ROOT>/config/atlas.toml`**（最底层）

`DATA_ROOT` 由你新加的 `ATLAS_DATA_DIR` 决定：不设 = `PROJECT_ROOT`（开发），设了 = `app.getPath('userData')`（打包版）。

⚠ **后果**：改完 `atlas.toml` 发现不生效，一定是 `user-settings.json` 在压。改网关时两层都要同步，或删掉 `user-settings.json` 让它回落到 toml。

---

## 3. 需要 Codex 配合/注意的三点

### ① 打包版数据目录已预置，不要用 example 覆盖它
我在 `C:\Users\25011\AppData\Roaming\Atlas\config\atlas.toml` 预置了与开发版一致的配置。`load_config()` 的逻辑是 `if not cfg_path.exists()` 才从 example 复制 —— 该文件已存在，**所以安装版首次启动会直接读到本地网关，不会回落到 example（无 key 状态）**。

### ② 千万不要把真实网关/密钥写进 `atlas.example.toml`
P8D 验收标准写着 **"No secrets included in package artifacts"**，而 `extraResources[2]` 会把 `../config/atlas.example.toml` 打进安装包。example 必须保持无凭据的模板状态。本机真实配置走 `%APPDATA%\Atlas\config\atlas.toml`（仓库外、不进包）——这条路才是对的。

### ③ 8765 端口已释放
调试用的后端服务已停止，端口干净。**你的打包版 Electron 验收（`ensureBackendRunning()` 探测 `http://127.0.0.1:8765/api/health`）不会撞到残留服务**，可以拿到真实结果。
（如果你需要对照一个已知健康的后端，手动起：`cd D:\Atlas\core && python -m uvicorn atlas.server:app --host 127.0.0.1 --port 8765`，或双击 `D:\Atlas\start-atlas.bat`。但**验收时请确保它没在跑**。）

---

## 4. 本次改动已通过的验证（供你参考，不用重跑）

配置改动经五层验证全绿：

```
1. 配置层   config.loaded path=D:\Atlas\config\atlas.toml
2. 模型层   model_manager.init api_base=http://127.0.0.1:8045/v1 default=gemini-3.8-flash-high
3. LiteLLM  acompletion 真调用 → model 回执 gemini-3.8-flash-high
4. HTTP     GET /api/health 200 · GET /api/models ⭐SELECTED · GET /api/settings/configuration api_key_configured=true
            POST /api/settings/test-connection → {"ok":true,"model":"gemini-3.8-flash-high","message":"模型连接测试成功。"}
5. WS 真对话 ws://127.0.0.1:8765/ws/chat 发 run.start
            事件序列 run.started → run.status → run.phase → message.delta ×2 → message.completed → run.phase → run.completed
            落库 ✓ conversations / messages / runtime_runs 三表均写入
```

---

## 5. 我没有碰的东西（你的施工范围完整保留）

- `core/atlas/config.py`、`frontend/src/main/electron.ts`、`frontend/package.json`、`README.md`、`package.json`、`package-lock.json` —— **你的改动一个都没动**
- `config/atlas.example.toml` —— 保持原样（含 `base_url = "https://api.monkeyapi.net"` 的无凭据模板）
- `frontend/release/`、`frontend/windows-release/` 里的内容 —— 只加了 gitignore，没动产物
- `voice-demo/` —— 未跟踪，未触碰

---

## 6. 顺带发现（不是你的锅，但值得你知道）

- `config/atlas.example.toml` 的 `[tools] auto_start = ["filesystem"]` 与实配的 `["filesystem","git","brave-search"]` **曾经漂移**：MCP 加载器的语义是「只遍历 `[tools.servers.*]` 里已定义的段，再按 auto_start 过滤」，所以 auto_start 里写了未定义的 server 名会被**静默忽略、不报错**。反向陷阱是 example 定义了 `git`/`brave-search` 段却没启。已把实配清理成只启 `filesystem`。
- `[tools.servers.brave-search]` 需要的 `BRAVE_API_KEY` 从未配置（example 里是空串）。

---

## 7. 追加（提交前安全净化 · 2026-09-26 · AI计划）

提交前扫描发现两处**真实凭据**会被推上 GitHub，已处理：

| 位置 | 问题 | 处理 |
|---|---|---|
| `ecosystem.config.js:17` | 原值为**真实 key**（14 字符、`sk-` 开头）—— 本文档第 1 节原写"占位 key"不实 | 改为 `process.env.ATLAS_API_KEY ?? ''`（凭据不入库；本地网关不校验 key），`node --check` 通过 |
| `voice-demo/config.json` (`llm.api_key`) | 未跟踪但含**同一个真实 key** | 加入 `.gitignore`，另生成脱敏的 `voice-demo/config.example.json` 入库 |
| `config/atlas.toml.bak-20260926-024700` | 原 `.gitignore` 只忽略精确名 `config/atlas.toml`，**备份后缀漏网** | `.gitignore` 增补 `config/atlas.toml.*` / `config/*.bak-*` / `*.bak-2026*` |

已确认 **GitHub 历史干净**：`HEAD:ecosystem.config.js` 无 `ATLAS_API_KEY` 行，
`git log -S"sk-"` 零命中 → 尚未泄露，无需轮换。

> 注：diff / grep 回显里的 `'***'` 是终端密钥脱敏造成的假象，真值确实是活 key。
> 判断某处是不是真凭据不能信回显，要看**值长度**、`git grep`、`git check-ignore`。

---

*生成：AI计划 · 2026-09-26 02:53 · Hermes 桌面端*
*第 7 节追加：AI计划 · 2026-09-26 03:4x*
