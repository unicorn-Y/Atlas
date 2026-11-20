# PAR-07 独立验收

验收日期为 2026 年 11 月 19 日，香港时间。验收对象是 ZCode 五包交付及 D 的后续修复树。本批五包暂缓合入。

| 包 | 已验证 | 验收缺口 |
| --- | --- | --- |
| A · CSV/TSV | 15 个 Vitest 用例和 renderer 类型检查通过。真实 FilesPanel 在隔离 Electron 窗口从文件树打开跨引号换行的分号 CSV，显示两列和正确数据单元格。 | 同一窗口点开内容为两个双引号的 CSV，界面仍提示「空文件，没有可显示的表格行」。解析器返回一行，组件将其过滤。补有引号空字段与真正空文件的渲染回归。 |
| B · 快捷键 | 7 个后端用例、11 个前端用例及类型检查通过。两个 Electron 窗口连接临时 Uvicorn 中的实际 u6 路由。窗口一保存返回 200，窗口二返回 409，原 revision 保持。 | 窗口二点击「用本机改动重试保存」得到 200，窗口一对不同操作的修改消失。应在最新文件上重放本次修改，验证两个不同操作均保留。 |
| C · 技能源 | 16 个定向用例通过。核对工作树中的配置覆盖、server 启动和 CLI 入口。CLI 预加载使用本次命令的 workspace。 | 桌面 server 启动时用默认 workspace 注册全局项目源，桌面 run 也使用全局管理器。另一个项目缺少自有项目源的解析接线。需要两个工作区的同名及独有技能验证。虚拟 provider 独立验收。 |
| D · worktree API | 修复树的生命周期与路由快照共 11 个用例通过。故障注入使用真实 FastAPI 路由、MemoryStore 与临时 Git 仓库。 | 记录失败且回滚被拒时，响应 500 声称已删除工作树，Git 仍列出 2 个工作树，会话无持久化 worktree_path。探针结束后清除了临时工作树。要正确报告回滚失败并支持识别和恢复残留。 |
| E · SDK 取消 | Python 3.11 环境的受影响套件 35 个用例通过。仓库 core/.venv 的 Python 3.14 环境 34 个通过、1 个失败，单独复跑同样失败。 | 3.14 下通知与迟到应答检查通过后，首次关闭的 SDK 子进程退出码为 1，后续持久化和重启断言未执行。主树 AppServer 与 Python SDK 两处补丁冲突。需要在当前实现上移植并复验关闭及重启。 |

## 位置

- A 在 zcode-exec06-csv-preview 的 frontend/src/renderer/shell/panels/csvPreview.tsx 第 139 行。
- B 在 zcode-exec06-keybindings-cas 的 frontend/src/renderer/pages/ShortcutsPanel.tsx 第 90–104 行。
- C 在 zcode-exec06-skill-sources 的 core/atlas/server.py 第 334–342 行及 core/atlas/api/run_drive.py 第 2546–2568 行。
- D 在 zcode-par07-worktree-api-fix 的 core/atlas/api/workspace_router.py 第 1648–1667 行。
- E 的退出断言在 zcode-par07-sdk-cancel 的 core/tests/test_app_server_user_question_cancel.py 第 523 行。

## 命令和边界

- A 的 Vitest 文件为 csvPreview.test.tsx、documentPreviewRegistry.test.tsx、FilesPanel.test.tsx。B 的 Vitest 文件为 keybindings.test.ts、shortcuts.test.ts、ShortcutsPanel.test.tsx。两包均执行 tsc -p tsconfig.renderer.json --noEmit。
- B 后端复跑 test_u6_keybindings.py，C 复跑 test_skill_sources_dsh.py，D 复跑 test_conversation_worktree_create.py、test_engine_worktree_pinned_revision.py、test_route_snapshot.py。
- E 两套 Python 环境均执行 pytest -o addopts=，覆盖 test_app_server_user_question_cancel.py、test_app_server_acp.py、test_app_server_sdk_lifecycle.py、test_event_contract.py 和 test_server.py::TestBackendParityWave1::test_ask_user_event_waits_for_a_response。
- 用 git apply --check 对主工作区只读检查五份补丁。A、B、C、D 修复树补丁可应用，E 的 core/atlas/tools/app_server.py 和 sdk/python/atlas_sdk/app_server.py 冲突。
- Electron 探针挂载实际产品组件和独立临时配置。A 通过本机 HTTP 提供临时文件夹具，B 连接真实 FastAPI 路由和临时 keybindings.json。未覆盖完整打包客户端启动。E 的真实 SDK 子进程使用本机模型夹具。
