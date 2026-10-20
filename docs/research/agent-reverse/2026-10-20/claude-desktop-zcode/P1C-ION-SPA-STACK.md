# P1C — 内置 SPA（`ion-dist`）的前端技术栈与路由

> 解决并深化 `U-010`（SPA 组件树）。全部来自 `index.html` 的 modulepreload 清单与 AST 扫描。
> 与前文的 `ION-MODULES.tsv`（模块级）互补：这里回答"它用什么框架、有哪些页面"。

---

## 1. 入口与模块图

`index.html` 只有一个 script 入口：

```
src="/assets/v1/index-D3kGySMO.js"
```

另有 **53 个 `modulepreload`**（Vite/rolldown 的预加载清单），它们按命名空间分组：

| 前缀 | 模块 |
|---|---|
| `rolldown-runtime-` | 打包器运行时 |
| `preload-helper-` | 动态导入助手 |
| `shared-<n>-` | 多份共享 chunk（0…N） |
| `vendor-` | 第三方依赖（见 §2） |
| `frame-` | Artifact frame 运行时 |
| `index-` | 应用入口 |

## 2. 第三方依赖（由 vendor chunk 名直接读出）

| vendor chunk | 对应库 | 说明 |
|---|---|---|
| `vendor-base-ui-` | **Base UI**（MUI 的无样式组件基座） | 组件原语 |
| `vendor-router-` | 路由库 | SPA 路由 |
| `vendor-query-` | TanStack Query | 服务端状态缓存 |
| `vendor-zod-` | Zod | 运行时 schema 校验 |
| `vendor-intl-` | FormatJS / react-intl | 国际化 |
| `vendor-markdown-` | Markdown 渲染 | 消息/artifact 渲染 |
| `vendor-tiptap-` | **TipTap** | 富文本编辑器 |
| `vendor-prosemirror-` | **ProseMirror** | TipTap 底层文档模型 |
| `vendor-motion-` | 动画库 | 过渡动效 |
| `vendor-icons-` | 图标集 | — |
| `vendor-growthbook-` | **GrowthBook** | feature flag SDK（与主进程的 growthbook 一致） |
| `vendor-datadog-` | **Datadog** | RUM/日志遥测（注意：与主进程用的 Sentry 是两套） |
| `vendor-utils-` | 工具函数 | — |
| `vendor-frame-` | 自定义 | Artifact 沙箱框架 |
| `vendor-all-` | 聚合 | — |

**这组名字本身就说清了产品形态**：Base UI + TipTap/ProseMirror 意味着**这是一个完整的富文本对话编辑器**，不是简易聊天框；GrowthBook 在前端也直接接入，说明 flag 是双端生效；Datadog 与 Sentry 并存，说明前端遥测与桌面端遥测分属两套系统。

## 3. 路由（AST 恢复，548 个路由对象 / 103 条唯一路径）

`ION-ROUTE-TABLE.tsv` 记录了 548 个带路径字面量的对象，去重 103 条。按顶级路径族统计：

| 族 | 出现次数 | 说明 |
|---|---:|---|
| `/admin-settings` | 416 | **企业管理员后台**（占绝对多数） |
| `/settings` | 53 | 用户设置 |
| `/new` | 15 | 新会话 |
| `/api` | 12 | API 相关页 |
| `/analytics` | 9 | 分析 |
| `/upgrade` | 7 | 升级/套餐 |
| `/projects` | 4 | 项目 |
| `/create` | 4 | 创建 |
| `/login` | 3 | 登录 |
| `/epitaxy` | 3 | （内部代号） |
| 其它 | — | `/artifacts`、`/code`、`/task`、`/repo`、`/releases`、`/people`、`/legal`、`/no-organization`、`/org-discovery`、`/abilities`、`/account-info`、`/s2`、`/v1`、`/v2`、`/graphql`、`/user`、`/downgrade` |

`/admin-settings` 下有完整的子树，例如：

```
/admin-settings/desktop-deployment
/admin-settings/desktop-deployment/{appearance,claude-code,connectors,limits,
                                   microsoft-365,overrides,plugins,telemetry,workspace}
/admin-settings/{api-access,artifacts,billing,billing/history,browser-extension,
                 capabilities,chat,claude-academy,claude-code,claude-design,
                 claude-in-slack,claude-science,claude-security,claude-tag,
                 cloud-environments,connectors,cowork,data-privacy-controls,
                 directory/submissions,grants,groups,inference-hooks,members,
                 models,notifications,office-agents,organization,plugins,
                 roles,skills,source-control}
```

**这张表就是 Claude 企业版的管理面全貌**，而且证明了 `desktop-deployment` 是一个真实存在的管理分类（含 connectors、plugins、telemetry、limits、overrides 五个子页）。

## 4. 关于"组件树"的边界说明（诚实）

`ION-COMPONENTS.tsv` 为 **0 行**。原因不是没扫，而是：该 SPA 由 rolldown 以 **`jsx()` 运行时调用**形式编译（非 `React.createElement` 字面量，也无 JSX 语法残留），且组件标识符已被压缩成单字母，**AST 层拿不到可读的组件名**。

因此"逐组件展开"在本样本上**不是"还没做"，而是"以现有二进制形态无法产出有意义的组件名"**。可以做的是：

- 已做：模块级（3,588 文件，imports/functions/classes 计数）、路由级（103 条）、依赖级（15 个 vendor）；
- 可做但未做：按 chunk 边界还原**代码分割图**（哪个路由加载哪些 chunk），这比组件名更有信息量；
- 不可做：还原 React 组件名（信息已丢失）。

## 5. 证据

| 断言 | 锚点 |
|---|---|
| 单入口 + 53 个 modulepreload | `ion-dist/index.html` |
| 15 个 vendor 分组 | 同上，`href="/assets/v1/vendor-*"` |
| 548 路由对象 / 103 唯一路径 | `ledgers/ION-ROUTE-TABLE.tsv` |
| 组件名为 0 | `ledgers/ION-COMPONENTS.tsv`（空）与 `ION-HOOKS.tsv`（空） |
| 3,588 文件全解析 | `ledgers/ION-MODULES.tsv` |

---

## 6. 全部 3,588 个 SPA 文件的逐文件归类（`ION-CLASSIFIED.tsv`）

| 类别 | 文件数 | 字节 |
|---|---:|---:|
| route/page chunk | **3,482** | 98,355,852 |
| shared chunk | 37 | 10,213,632 |
| frame runtime asset | 32 | 4,520,926 |
| artifact frame (shell) | 7 | 3,875,853 |
| worker | 6 | 1,867,530 |
| artifact frame | 3 | 221,471 |
| wasm loader（tree-sitter / oniguruma） | 2 | 640,686（含 622 KB 内联 base64 WASM） |
| app entry | 1 | 67,568 |
| audio worklet | 1 | 67,634 |
| bundler helper / runtime | 2 | 4,828 |
| vendor（15 个分组） | 15 | 1,738,331 |
| **合计** | **3,588** | **121,566,830** |

**未分类 = 0。**

### 说明

- `route/page chunk` 占 96.8% 的体积 —— 这是 rolldown 的路由级代码分割，每个路由一个 chunk（3,482 个），与 P1C 第 4 节"103 条唯一路由"并不矛盾：**一条路由可以对应多个 chunk**（组件、loader、样式各自分包）。
- `vendor:*` 15 组与第 2 节的依赖表完全对应（base-ui / datadog / frame / growthbook / icons / intl / markdown / motion / prosemirror / query / router / tiptap / utils / zod / all）。
- `artifact frame` 系列共 10 个文件（shell 7 + runtime 3 + _frame-rt 下的 32 个资源），是 Artifact 沙箱外壳的完整实现。

**这份表的价值**：此前只能说"3,588 个文件全部解析成功"，现在能说"每一个文件属于哪一类、占多少体积"。逐文件语义的边界仍然存在（组件名不可恢复），但**没有未归类的文件**。
