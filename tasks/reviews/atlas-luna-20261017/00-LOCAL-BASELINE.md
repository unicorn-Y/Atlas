# 本机运行基线（2026-10-17）

状态：审查进行中；本文件记录本轮观察，不继承旧审计的通过结论。

## 来源与保全边界

- 任务书从 GitHub `unicorn-Y/Atlas` 分支 `task/luna-audit-model-policy-20261017` 的 `tasks/taskbooks/ATLAS-LUNA-GLOBAL-AUDIT-MODEL-RETRY-20261017.md` 完整读取。
- 用户源码目录：`D:\Atlas`；当前分支 `ui-redesign`；HEAD `0b1ba4114e25643369c95bfac85d37563788444f`。
- 该目录存在 12 个已跟踪文件的未提交修改，以及未跟踪源码、报告、图片和运行目录。因存在磁盘修改，HEAD 不代表当前全部源码内容。
- W1 代码在 `D:\atlas-luna-w1-20261017` / `fix/atlas-model-retry-policy-20261017` 施工；审查汇总在 `D:\atlas-luna-review-20261017` / `review/atlas-luna-global-audit-20261017`；W0、W2–W7 各自使用独立 detached worktree。
- 禁止修改用户主目录、真实记忆与会话、运行进程或安装依赖；未执行启动脚本、分支切换、stash、reset、clean、pull 或合并。抓取远程 refs 使用 `git fetch origin '+refs/heads/*:refs/remotes/origin/*'`。

## 进程与端口绑定

本轮通过 `Win32_Process` 与 `Get-NetTCPConnection -State Listen` 交叉观察：

| 层级 | PID / 父 PID | 启动与绑定 | 判定 |
|---|---|---|---|
| Electron 主进程 | 55644 / 71604 | `D:\Atlas\node_modules\electron\dist\electron.exe --remote-debugging-port=9335 --remote-allow-origins=* D:\Atlas\frontend` | 确认桌面来自该源码工作区 |
| Python 启动器 | **51284** / 55644 | `D:\Atlas\core\.venv\Scripts\python.exe -m atlas.desktop_entry`，2026-10-17 16:54:17 启动 | Electron 子进程 |
| Python 后端 | **50140** / 51284 | 同上；cwd 实测 `D:\Atlas\core`，2026-10-17 16:54:17 启动 | `127.0.0.1:8765` 监听归属此 PID |
| CDP | 55644 | `127.0.0.1:9335` | 与上述 Electron 相符 |

> **第三轮更正（2026-10-17 17:36）**：审查收尾时后端再次重启，8765 现由 **PID 70348**（父 33572，17:36:05 启动，命令 `D:\Atlas\core\.venv\Scripts\python.exe -m atlas.desktop_entry`）持有。这是**本机正常使用中的重启**，不是本轮操作导致——本轮对 `D:\Atlas` 全程只读（收尾核对仍为 HEAD `0b1ba411` + 12 tracked modified + 41 untracked，与开始时一致）。三次观测到的 PID 依次为 1800/53140 → 51284/50140 → 33572/70348，**命令行与 cwd 始终是 `D:\Atlas\core`**，故「运行内容 = 工作区快照」的结论不随 PID 变化。
>
> **第二轮更正（2026-10-17）**：上表原记 PID 1800 / 53140，复核时该两个进程已退出，当时进程为 51284 / 50140（16:54:17 启动）。用 psutil 读取工作进程 `cwd` 得 `D:\Atlas\core`，确认 8765 这条用户日常链路源码根为 `D:\Atlas`。另有一条独立实例 `D:\atlas-mem-integrate\core` 跑在 9459（PID 37200 / 46164，16:09 启动），不在本轮范围。详见 `07-INCREMENT-RECHECK.md §1`。
>
> **运行内容是 HEAD 还是工作区**：已收口为「`0b1ba411` + 12 处未提交修改的工作区快照」。判据：`expert_harness.py`(12:16:39)、`model_call.py`(01:05:41)、`run_phases.py`(02:53:40)、`loop.py`(01:05:21) 的 mtime 全部早于后端启动 16:54:17；且 `cwd=D:\Atlas\core` 使 `atlas` 包解析到该目录。

只读 HTTP 观察：`GET /api/health` 返回 200，`status=ok, version=0.1.0`；`GET /v1/ready` 返回 404；CDP `/json/version` 返回 200（Chrome/152.0.7977.130，协议 1.3）。这些只证明相应端点的状态，不证明聊天、工具、记忆或生命周期端到端成功。`/v1/ready` 404 亦不单独定为缺陷，须结合当前版本就绪接口设计。

## 引擎与配置指向

- 磁盘 `engine/config.yaml:12` 为 `engine: auto`，`:20` 为 `provider: auto`，`:21` 的模型为空。这些是配置文件观察，不足以确认当前会话实际选用模型。
- `frontend/src/main/backendProcess.ts:560–564` 区分打包后端和源码候选，源码候选 `cwd=coreDir`；`:39–40` 允许 `ATLAS_DATA_DIR` 覆盖。
- `core/atlas/desktop_entry.py:14` 的早期路径选择会读取 `ATLAS_DATA_DIR`，否则定位源码 `core/data`；启动代码及 AppConfig 的进一步根目录选择由 W6 补充核查。
- `core/atlas/agent/run_phases.py` 的本轮实际文件调用 `HermesRuntime` 并向内核传入选择的模型；W1 已确认当前主会话路径为 AtlasKernel 的 `complete_stream`。进程内已加载代码、启动时环境和会话具体模型仍须区分于磁盘静态推断。
- 对 `GET /api/settings/configuration` 的只读响应仅提取白名单字段：HTTP 200；当前默认模型 `deepseek-v4.1-flash`，provider `openai`，配置来源 `user-settings`；记忆模型 `gemini-3.8-flash`，压缩模型和子代理默认模型为空；目录提供 10 个模型，密钥仅记录 `api_key_configured=true` 布尔值。这是实时默认设置，不代表每个既有会话的独立模型选择。
- 对应接口证据：`core/atlas/api/models_settings_router.py:117`（入口）、`:134–150`（白名单字段来源）；配置根目录证据 `core/atlas/config.py:27–32`，`ATLAS_DATA_DIR` 存在时配置及数据根均覆盖，否则根为项目。
- 未显示或保存任何凭据值，未读取用户会话/记忆内容；设置接口响应只输出上述白名单摘要。尚未取证的启动环境、实际进程已加载模块与本轮磁盘修改的先后顺序标记为待核实。

## 已跟踪未提交修改清单

1. `core/atlas/agent/results.py`
2. `core/atlas/agent/run_phases.py`
3. `core/atlas/agent/tool_catalog.py`
4. `core/atlas/agent/tool_node.py`
5. `core/atlas/engine/hermes_runtime.py`
6. `core/atlas/kernel/loop.py`
7. `core/atlas/kernel/model_call.py`
8. `core/atlas/kernel/plan.py`
9. `core/atlas/kernel/tools.py`
10. `core/atlas/tools/web.py`
11. `engine/config.yaml`
12. `frontend/src/renderer/components/timeline.ts`

主执行者已为这 12 个文件计算内容 SHA-256；收口复核12个hash全部未变，HEAD、分支和完整porcelain状态亦未变。不上传配置文件内容。W1只读比较涉及模型链路的dirty代码，属于expert prompt、web research、filter guidance等差异，策略补丁基于HEAD独立完成；未复制或覆盖主目录dirty文件。独立前后端diff复核未发现必须吸收dirty代码才能实施W1的阻断。

## 分支盘点与尚未确认项

全远程分支及本地 worktree 未推送差异由 [01-ALL-BRANCHES.md](01-ALL-BRANCHES.md) 汇总。旧审计、旧测试结果均为线索，不复用为本轮实测结论。仍须在收尾核实主工作区指纹、W1 测试与远端提交一致性、完整 405 条功能证据和未覆盖项。
