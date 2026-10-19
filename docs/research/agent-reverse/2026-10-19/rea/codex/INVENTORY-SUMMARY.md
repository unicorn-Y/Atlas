# 标本清单摘要（INVENTORY SUMMARY）

## 一、登记总表

| 容器 | 文件数 | 字节数 | 说明 |
|---|---|---|---|
| `ChatGPT-x64.msix`（解包） | 3,651 | 2,346,419,207 | Electron 应用 + Chromium 框架 |
| `app.asar`（解包） | 21,073 | 593,720,176 | 主进程 bundle + webview 资源 + 内嵌 CLI 源码树 |
| `openai-codex-cli-x64.zip` | 47 | 491,000,000+ | 含 codex.exe 341 MB、voice 组件、rg、sandbox setup |
| `code-mode-host.zip` | 1 | 74,921,264 | 单一可执行文件 |
| Rust 源码快照 | 9,176 | ~108 MB | 155 crate / 5,276 .rs |
| **合计（files.jsonl）** | **12,875** | **3,003,835,662** | |

> 注：`files.jsonl` 的 12,875 是"解包后的叶子文件"；`app.asar` 的 21,073 条目是 asar 容器内部成员，已全部解出到 `extracted/desktop-asar/`，但为避免重复计入，`files.jsonl` 以解包后的物理文件为准。两份清单都在 `indexes/` 中。

## 二、按类型分布（MSIX 解包）

| 扩展名 | 数量 | 说明 |
|---|---|---|
| `.js` | 1,278 | 内嵌 CLI 源码 + webview 少量 |
| `.pak` | 223 | Chromium 资源包（不承载 Codex 逻辑） |
| `.ts` / `.cc` / `.h` | 499 / 331 / 326 | 内嵌 CLI 源码树（含原生模块） |
| `.md` | 320 | 文档 |
| `.json` | 114 | 配置 |
| `.exe` | 20 | 主程序 + 辅助进程 |
| `.dll` | 19 | Chromium 框架 + 原生模块 |
| `.png` / `.svg` | 47 / 17 | 图标与资源 |
| `.node` | 52 | 原生模块 |
| 其他 | 1,000+ | 字体、locale、资源 |

## 三、关键二进制清单

| 文件 | 大小 | 作用 | 分析深度 |
|---|---|---|---|
| `app/ChatGPT.exe` | 4,795,184 | Electron 启动器 | 未反编译（行为由 asar 覆盖） |
| `app/resources/codex.exe` | 341,312,816 | **Agent Runtime** | 字符串级 + PE 结构 |
| `app/resources/codex-code-mode-host.exe` | 74,921,776 | Code Mode 宿主 | 字符串级（gRPC 方法表已提取） |
| `app/resources/codex-command-runner.exe` | 8,217,392 | 沙箱命令代理 | 字符串级（协议结构已提取） |
| `app/resources/codex-windows-sandbox-service.exe` | 55,824,688 | Windows 沙箱服务 | 未分析 |
| `app/resources/codex-windows-sandbox-setup.exe` | 17,700,144 | 沙箱安装器 | 未分析 |
| `app/chrome.dll` | 大 | Chromium | 不分析（框架） |
| `app/resources/codex-resources/voice/bin/codex-voice-host.exe` | — | 语音宿主 | 未分析 |

## 四、是否与清单一致

| 项 | 清单登记 | 实测 | 结论 |
|---|---|---|---|
| MSIX SHA256 | `e2d892e6…be7f` | 一致 | ✅ |
| CLI ZIP SHA256 | `dabdb4d1…04c3` | 一致 | ✅ |
| Code Mode Host SHA256 | `bc82fa6d…de68` | 一致 | ✅ |
| 源码 ZIP SHA256 | `36fda4e6…67c7` | 一致 | ✅ |
| MSIX 版本 | 26.1013.4894.0 | 与官方 update json 一致 | ✅ |
| CLI 版本 | 0.163.0 | `--version` 实测一致 | ✅ |

## 五、本地保留与 Git 的边界

- **本地全量保留**：`D:\Atlas-Reverse-Lab\codex\input\`（原始包）、`extracted\`（解包）、`decompiled\`（反编译/字符串）、`indexes\`（索引）
- **Git 只放轻量产物**：报告、协议 schema 摘要、索引 JSON、viewer、2 张截图
- 原始包与完整解包**不进 Git 历史**（体积 3 GB+）
