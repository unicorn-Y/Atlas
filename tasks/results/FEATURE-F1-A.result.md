# FEATURE-F1 A 区交付记录

## 工作树与分支

- 工作树：`D:\atlas-f1-a`
- 分支：`f1-a`，基于创建时的 `origin/memory-v1`
- 原工作目录 `D:\Atlas` 未修改。
- 本记录随实现提交；最终 SHA 由提交后回填。

## A 区实现

- 会话列表默认完整读取，并支持偏移、分页、归档、置顶、工作区和标题/ID/摘要筛选。
- 侧栏新增搜索、筛选、分组、排序、自定义组、拖动归类、多选归档/删除、项目会话导航、项目批量归档确认、手动未读、队列数量、运行/等待状态、目录打开与后续工作目录选择等入口。
- 新增会话详情，展示会话元数据、用户轮次、运行记录、输入/输出 Token 和可用的费用估算。
- 新增当前会话全文查找 API 与详情面板，返回最近匹配消息及上下文片段；无价格数据时明确展示未知状态。
- 项目列表支持按需返回关联会话；日志路径操作复制 Atlas 共享 SessionDB 路径并明确其共享属性。
- ZCode 固定提交的侧栏交互模式已在源码头标明；许可说明追加至 `THIRD_PARTY_NOTICES.md`。
- V5 矩阵 A01–A45 与附录 VI–IX 的 A 区更正已逐项核对；额外类别和跨区依赖分别记录在 parity 清单中。

## 验收记录

- `npm --prefix frontend run build`：通过，exit code 0。
- 测试：未新增、未运行任何测试或测试套件。
- 后端：设置 `ATLAS_UPSTREAM_AUTO=0` 并使用临时 `ATLAS_DATA_DIR` 启动时，曾观测到 `Application startup complete`，且 `/api/health` 返回 200；`/api/conversations` 与 `/api/tools` 也曾在该实例返回 200。之后本机反复启动会在 Hermes `run_agent.py` 的环境启动路径上以 `RelaunchExit: 1` 退出，无法保持稳定服务。
- 源码路由检查：工作树导入的 `atlas.server` 来自 `D:\atlas-f1-a\core\atlas\server.py`；工作树 OpenAPI 路由表包含新增的 `/api/conversations/{conversation_id}/stats` 和 `/search`。
- 界面：用本机 Chrome 打开 renderer，使用临时 API 夹具载入会话，实际打开侧栏会话菜单、会话详情、轮次与用量区和查找输入；搜索返回匹配片段，过程中无页面异常。使用短命真实后端进程时，详情端点得到通用 404，显示该进程未提供工作树新增路由；因此实时后端到新增端点的端到端调用尚未确认，夹具界面结果不作为真实后端 API 通过证据。

## 记录的未完成跨区或产品边界

以下条目已保留在 `docs/parity/F1-A.md` 与 `docs/parity/F1-unassigned.md`，不以静态 UI 或伪造状态冒充能力：公开分享链接及片段范围、项目多窗口/浮动窗、远程服务器注册与跨设备配对、模型轨迹/跨会话 Agent View、PR 状态徽章、Worktree 创建/迁移/清理及自动清理策略、云项目/移动 Dispatch。它们依赖 C/D 区设置、服务端集成、B 区消息/轨迹视图或 Git 工具。

其余未实现的单产品导航或生命周期差异（例如上一条/下一条专用控件、ZCode 自动归档期限）在 A 清单中明确标成差异，没有写成已支持。

## 提交与推送

- 最终 SHA：待提交后回填。
- 推送目标：`origin f1-a`；不推送 `memory-v1`。
