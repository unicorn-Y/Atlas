# 13 — 覆盖率与验收

> 所有分子分母均可由 `ledgers/` 下的表复算。独立审计脚本：`scripts/audit_p8.py`（从原始 MSIX 重新生成清单再求差，不读取任何先前结论）。

---

## 1. 文件登记率

| 检查 | 分子 | 分母 | 结果 |
|---|---:|---:|---|
| MSIX 文件登记 | 4,443 | 4,443 | **100%** |
| MSIX 哈希复验（独立重算） | 4,443 | 4,443 | **0 不符** |
| MSIX 缺失项 | 0 | — | — |
| MSIX 多余项 | 0 | — | — |
| ASAR 路径登记 | 548 | 548 | **100%** |
| ASAR 文件 | 506 | 506 | 100% |
| ASAR 目录 | 42 | 42 | 100% |
| ASAR 文件分类（`MODULE-CLASSIFICATION.tsv`） | 506 | 506 | **100%** |
| 未分类 ASAR 文件 | 0 | — | — |

## 2. 容器嵌套

| 容器 | 内部项 | 登记 |
|---|---:|---|
| MSIX → ASAR | 1 | ✅ |
| ASAR → `.skill` ZIP ×6 | 6 | ✅ |
| `.skill` 内部文件 | 188 | ✅ 全部含 SHA256 |
| ASAR → `app.asar.unpacked` | 6 | ✅ |
| MSIX → PE 二进制 | 18 | ✅（架构/子系统/版本/签名） |

## 3. 代码级覆盖

| 层 | 已处理 | 总数 | 覆盖率 | 说明 |
|---|---:|---:|---:|---|
| 主进程 JS/MJS/TS | 435 解析成功 | 437 | 99.5% | 2 个失败为 `agent-base/*.d.ts` 类型声明，无运行代码 |
| 内置 SPA JS | 3,588 | 3,588 | **100%** | acorn 全解析，0 失败，121,560,060 B |
| Go 函数（4 个二进制） | 23,018 | 23,018 | **100%** | pclntab 全量：cowork-svc 15,181 + ssh 三件套 7,837 |
| PE 二进制 | 18 | 18 | **100%** | 含 Authenticode 验证 |
| Worker | 7 packaged | 7 | **100%** | 8 个目录中 `mcp-runtime` 是 MCP host 不是 worker；`shell-path-worker` 在本构建中**无 spawn 点** |

## 4. 接口配对

| 检查 | 结果 |
|---|---:|
| eipc 服务 | 97 |
| eipc 方法 | 1,170 |
| eipc 事件 | 162 |
| RPC 条目合计 | **1,332** |
| 有可达调用者（PAIRED） | **1,332（100%）** |
| 无调用者的 handler | **0** |
| 无 namespace 的孤岛服务 | **0** |
| 传输层注册点（原始） | 1,609 |
| Electron channel 级配对闭合 | 3 / 1,232 —— **已解释**：单 channel 多路复用，正确单位是方法级 |
| `contextBridge` 暴露 | 52 |
| MCP 工具声明（从二进制恢复） | **200 行**（github 137 字面量≈135 去重 / office365 50 工具+10 资源处理器 / runtime 3） |
| `webContents` 原生事件 | 60（非 IPC，无需配对） |

## 5. UI 覆盖

| 对象 | 数量 |
|---|---:|
| 界面对象（窗口/视图/弹窗/离屏/对话框/托盘/菜单） | **26** |
| 菜单项 | 99（应用 82 + 右键 13 + 托盘 4） |
| 快捷键 | 57 |
| 路由（桌面外壳视角） | 64 |
| 路由（内置 SPA 视角） | 716 |
| 每个界面可触及的 eipc namespace | 已逐窗登记（13 个 preload 全覆盖） |
| mainView 接通的 eipc 方法 | **1,127**（81 服务）+ 6 个 WindowManager = 1,133 |
| 其它窗口私有服务 | 11 个服务 / 43 个方法 |

**未闭合**：远程 UI（1P 模式下从 claude.ai 加载）的组件级链路，物理上不可静态获取 → `CLOUD-UNAVAILABLE`。

## 6. 配置面覆盖

| 对象 | 数量 |
|---|---:|
| Feature flags 条目 | 380 |
| Feature flags 唯一键 | 186 |
| 环境变量 | 1,062 |
| 网络端点（唯一 URL） | 405 |
| 字符串枚举成员 | 1,179（127 张表） |
| 持久化文件名 | 20+（`.claude/projects`、`settings.json`、`spaces.json`、`scheduled-tasks.json`、`artifacts.json`、`window-state.json`、`auth.json`、`msal-cache.json`…） |

## 7. 证据等级分布

| 等级 | 含义 | 本报告使用情况 |
|---|---|---|
| **S** | 真实源码/二进制/符号/调用链，有定位 | 绝大多数结论 |
| **R** | 同版本真实运行 | **0**（按任务书纠偏，运行取证已移入 `out-of-scope/`，不计分） |
| **D** | 官方文档声明 | 0（本报告未引用官方文档作为实现证据） |
| **I** | 推断，附依据 | 少量（如"host loop 模式语义"） |
| **U** | 未解释 | 21 项，见 `12-UNKNOWN-AND-BLOCKERS.tsv` |

## 8. 未解清单统计

| 状态 | 数量 | 类别分布 |
|---|---:|---|
| RESOLVED（本轮内已解决） | **14** | 3 个 WASM 身份、gated-imports、scc.json、handleEvent 事件名、帧协议/10MiB/100MiB、handlePassthrough 目标、nodeHost vs directMcpHost |
| PARTIAL（部分解释） | 8 | 代号服务、SPA 组件树、两版 diff、Claude Code CLI 参数等 |
| CLOUD-UNAVAILABLE | 2 | 服务端 agent loop、1P 远程 UI |
| DEFERRED（形态受限） | 1 | SPA 组件名不可恢复（无 sourcemap） |
| UNKNOWN | 2 | SSH 中继管道路径、代号服务含义 |
| **合计** | **32** | — |

## 9. 独立审计（从原始包重新生成，不看本报告结论）

脚本 `scripts/audit_p8.py` 的动作：
1. 重新打开 `claude-desktop-x64-2bf309665f.msix`；
2. 重新遍历全部 zip 条目；
3. 重新解析 `app.asar` 头部，重建 ASAR 文件/目录集合；
4. 与本报告 `ledgers/FILE-LEDGER.tsv` / `ASAR-FILE-LEDGER.tsv` / `MODULE-CLASSIFICATION.tsv` 求差；
5. 对每个已登记文件**重新计算 SHA256** 并与登记值比对。

结果（`ledgers/AUDIT-P8.json`）：

```json
{
  "msix_files_source": 4443,
  "msix_files_registered": 4443,
  "msix_missing_count": 0,
  "msix_extra_count": 0,
  "asar_files_source": 506,
  "asar_dirs_source": 42,
  "asar_files_registered": 506,
  "asar_missing_count": 0,
  "asar_extra_count": 0,
  "classified_paths": 506,
  "unclassified_count": 0,
  "hashes_reverified": 4443,
  "hash_mismatch_count": 0
}
```

**差集全部为空，哈希零不符。**

## 10. 验收判定（逐条对任务书门槛）

| 门槛 | 判定 | 说明 |
|---|---|---|
| 文件登记率 100%（含嵌套容器） | **PASS** | 4,443 + 548 + 188 + 18 全登记 |
| 每个注册点/界面入口有状态与证据 | **PASS** | 1,332 RPC 全配对；27 界面全带文件+偏移锚点 |
| 重要业务机制端到端链 | **PARTIAL（但 Service/VM 已达指令级）** | Chat（3P 本地可闭合，1P 云端不可）、Cowork（VM 链路完整）、Artifact（24 方法全）、Scheduler（3 服务）、MCP（101 方法）、Service/VM（15,181 函数，管道分发表与帧格式已指令级证实）、状态/恢复（4 条路径）——**但均为静态链，无运行时闭合** |
| 独立复查新发现 | **PASS** | 本轮新挖出：195 MB 内置 SPA、c2pa/clarkdown/tree-sitter WASM、EDR 接入、gVisor 网络栈、7 路推理后端、1,062 环境变量 |
| 不把"已登记"升级为"全部逆向" | **PASS** | 明确区分 CLOUD-UNAVAILABLE 与 PARTIAL |
| 仍有可做项时不得宣布结束 | **见下** | 仍有明确可做项（见 §11） |

## 11. 仍可继续的明确工作（未做，不隐藏）

| 项 | 工作量估计 | 价值 |
|---|---|---|
| ~~`ion-dist` React 组件树展开~~ | — | **受限**：组件名在压缩+jsx() 编译下不可恢复；改为可做的 chunk 级代码分割图 |
| `cowork-svc` 15,181 函数中的关键 handler 逐指令反汇编 | 中 | 高（协议字节序、10 MiB 上限） |
| ~~2.42304.0 vs 2.42304.2 逐文件 diff~~ | — | **已完成**：见 `VERSION_DELTA.md`，唯一实质变化是 nodeHost CA 屏蔽 |
| `nodeHost` vs `directMcpHost` 逐行 diff | 小 | 中 |
| 5 个代号服务（GrandPrix/ForgeState/Gorse/ViolinFret/WebBuild）的调用方追踪 | 中 | 中 |
| 3P 模式下的完整 UI → RPC 映射（因 SPA 已在包内，可静态做） | 大 | 高 |

## 12. 最终状态

**PARTIAL** —— 静态分解达到文件/函数/注册点粒度且经独立审计零差异；但因上表 6 项仍有可做工作，按任务书规则不宣布 COMPLETE。
