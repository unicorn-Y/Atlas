# P1 补充修正 — 被"资源"标签掩盖的 201 MB 第一方前端（`ion-dist`）

> 本条是对 `P1-STATIC-CODE-INVENTORY.md` 的**实质性修正**，必须与 P1 正文一并阅读。
> 触发原因：在 P6 排查"未解目录"时发现 `app/resources/ion-dist/` 被 P0/P1 归类为 `resources` 层，实际容量占整个 MSIX 的 95%。

---

## 1. 规模事实（S，全部可由 `FILE-LEDGER.tsv` 复算）

| 项 | 数值 |
|---|---:|
| `ion-dist` 文件数 | **4,224** |
| `ion-dist` 总字节 | **199,562,129**（199.5 MB） |
| 占 MSIX 全部 4,443 条目的比例 | **95.0%** |
| 占 MSIX 解压后总量（728.9 MB）的比例 | **27.4%** |

内部构成：

| 子目录 | 字节 | 内容 |
|---|---:|---|
| `assets/` | 156 MB | **3,554 个 `.js`**、25 个 `.css`、340 个 `.svg`、40 个 `.woff2`、3 个 `.wasm`（最大 8.25 MB）、若干 GIF/WEBP |
| `i18n/` | 35 MB | 多语言资源 |
| `_frame-rt/_runtime/` | 5.5 MB | 字体（AnthropicSans/Serif/Mono、anthropicons）+ `artifact.*.js` 运行时 |
| `audio/voice/` | 3.1 MB | 语音相关音频 |
| `images/` | 1.9 MB | 图片 |

根级 HTML：`index.html`（46,664 B，`<title data-react-fallback>Claude</title>`）、`client-shell-v1.html`、`frame-shell.html`（`<title>Artifact</title>`，26,317 B）、`frame-connect.html`、`frame-manage.html`，以及 `scc.json`、`custom-3p-gated-imports.json`、`robots.txt`、`third-party-notices.txt`。

`index.html` 的构建标记：`data-build-id="spa-dev"`、`data-git-hash="local"`、`data-version="1.0.0"`、`data-theme="claude"`、`class="cds-root"` —— 这是 **Claude 自有的 CDS 设计系统 SPA**，不是第三方框架产物。

## 2. 它是什么（S）

`ion-dist` 是**完整打包的 Claude Web 前端（SPA）**，随安装包本地交付。

- 主进程通过 `k8r(path.join(<resources>,"ion-dist"), <rendererConfigProvider>)` 安装 `app://` 协议处理器，把该目录作为协议根。
- 本地 origin 常量为 `ql = "app://localhost"`。
- `client-shell-v1.html` / `frame-shell.html` / `frame-connect.html` / `frame-manage.html` 分别是**客户端外壳、Artifact frame、连接页、管理页**。

## 3. 本地 SPA 与远程站点如何二选一（S，关键）

主进程有两套 deployment 实现，同一个方法 `getMainWindowUrl()` 返回不同值：

```js
// 标准（1P）部署
getMainWindowUrl(){ return this.deps.anthropicOriginUrl() }   // → https://claude.ai

// 第三方（3P）部署
getMainWindowUrl(){ return ql }                               // → app://localhost
```

切换依据是持久化的部署模式：

```js
PERSISTED_DEPLOYMENT_MODE_KEY = "deploymentMode"       // 存于配置文件
readPersistedDeploymentMode()  // 只接受 "3p" | "1p"
deploymentModeIs3p()           // 对外暴露
resolve3pForcingSource()       // 由 managed config 决定是否强制
```

并且 `buildConfig()` 明确输出 `is3p: true` 或 `false`。

**结论**：

| 部署模式 | 主窗口 URL | UI 来源 |
|---|---|---|
| `1p`（Anthropic 托管） | `https://claude.ai`（或 `preview.*`、`.ant.dev`） | **远程站点** |
| `3p`（企业自建/第三方） | **`app://localhost`** | **本地 `ion-dist` SPA** |

这解释了为什么 `ion-dist` 必须随包交付：**企业部署不允许连 claude.ai 渲染 UI**（对应 flag `disableConnectorSignInInApp`、`selfHostedEndpoint`、`bootstrapUrl`），因此把整个前端打进安装包，由 `app://` 协议本地提供。

## 4. 对 P1 结论的修正

P1 原文写「主窗口 UI 是远程的」，依据是 `main_window/index.html` 的注释：

> `<!-- this is the html for app title bar and error UI. everything else gets loaded from claude.ai -->`

**该结论只在 1P 模式下成立。** 准确表述应为：

- `.vite/renderer/main_window/index.html` 是**窗口外壳**（标题栏、错误页、启动占位），两种模式都用它。
- 其内容区在 **1P 模式**下由 `loadURL(https://claude.ai)` 填充；在 **3P 模式**下由 `loadURL(app://localhost)` 填充，而 `app://localhost` 映射到包内的 `ion-dist`（4,224 文件 / 199.5 MB）。
- 因此 **"Claude 的聊天 UI 代码不在安装包里"是错误的**。它在包里，只是 1P 模式不用它。

## 5. 由此产生的新的追踪任务（已列入 P8 待办）

`ion-dist` 的 3,554 个 JS 是**第一方前端代码**，此前完全未做 AST 分析。必须补做：

1. 对 `assets/v1/*.js` 建立模块/符号索引（与主进程 chunk 同等深度）；
2. 识别路由表（SPA 内部 router）、页面组件、状态管理；
3. 找出 SPA → `app://`/eipc 的桥接点（它如何调用 97 个 eipc 服务）；
4. 3 个独立 `.wasm` 的用途（最大 8.25 MB）——**另有第 4 个以 base64 内联在 `assets/wasm-*.js`（Oniguruma 正则引擎）**，见 `P6H`；
5. `_frame-rt/_runtime/artifact.*.js` 与 `frame-shell.html` 的 Artifact 渲染沙箱实现。

## 6. 证据

| 断言 | 锚点 |
|---|---|
| 4,224 文件 / 199,562,129 B | `ledgers/FILE-LEDGER.tsv`（路径前缀 `app/resources/ion-dist/`） |
| `app://` 处理器安装 | `.vite/build/index.chunk-lzaSYO3Q.js`：`k8r(path.join(uIa(),"ion-dist"), ...)` + `"Failed to install app:// protocol handler"` |
| `ql="app://localhost"` | 同文件：`var ql="app://localhost",UVe="00000000-0000-4000-8000-000000000001"` |
| 两套 `getMainWindowUrl` | 同文件，分别返回 `ql` 与 `this.deps.anthropicOriginUrl()` |
| 部署模式持久化 | 同文件：`PERSISTED_DEPLOYMENT_MODE_KEY="deploymentMode"`、`readPersistedDeploymentMode()` 接受 `"3p"|"1p"` |
| 合法 sender origin 名单 | 同文件多处：`https://claude.com`、`https://preview.claude.com`、`app://localhost`、`.ant.dev`、开发态 `localhost`、打包态 `file:` |
