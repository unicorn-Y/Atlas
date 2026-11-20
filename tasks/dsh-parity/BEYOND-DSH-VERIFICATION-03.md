# X6 插件兼容准入：独立验证截点

日期：2026-11-16。生产实施：用户指定 Codex Desktop GPT-6 Luna 高，经主控本机 CDP 派工。主控不代写生产实现。仍非全任务验收。

## 独立测试

工作目录 D:/Atlas/core，Python 为既有 hermes-agent venv。每次 pytest 使用唯一 --basetemp，进程自然退出。

```text
python -m pytest tests/test_plugin_compatibility.py -q -p no:cacheprovider --basetemp=<唯一 atlas-x6-first-supervisor>
17 passed, 5 warnings in 2.58s
INDEPENDENT_EXIT_CODE=0

python -m pytest tests/test_plugin_compatibility.py -q -p no:cacheprovider --basetemp=<唯一 atlas-x6-lifecycle-supervisor>
19 passed, 5 warnings in 3.35s
INDEPENDENT_EXIT_CODE=0

node node_modules/vitest/vitest.mjs run --root D:/Atlas/frontend src/renderer/pages/ConsolePage.compatibility.test.tsx
Test Files 1 passed; Tests 1 passed; Duration 273ms

node node_modules/typescript/bin/tsc -p D:/Atlas/frontend/tsconfig.renderer.json --noEmit
exit 0
```

5 warnings 是已有 FastAPI on_event / Pydantic Config 弃用。首批17项不覆盖后续生命周期新测试；第二截点19项为后续实际结果，不相加成36项。

## 已观察的实现范围

- npm peer range 复用 semantic_version.NpmSpec，运行时版本来自 atlas.__version__，不再自写 PEP440 子集或复制版本号；依赖加入 core/pyproject.toml。
- manifest peer mismatch 与精确插件版本/运行时版本豁免；grant 必须显式 acceptRisk=true，版本变动不沿用。
- 已补最深 _load_one、load_all、reload/enable/install 及 enabled_contributions 的共同准入；共享技能、命令、agents、lazy hooks 供应者不能只看 enabled。
- API grant/revoke 与桌面显式勾选风险、豁免/撤销交互。

具体覆盖边界以当前测试实现为准。

## 不能冒充的证据

- 能力注册测试使用真实 AgentCapabilityRegistry，但 MCP 为 _FixtureMCP 对象，不是实际 MCP 协议/子进程。
- HTTP 测试用 FastAPI TestClient，_reload_extensions 被接到本地 apply_plugins 函数，未启动真实后端 lifespan。
- 桌面组件测试使用 react-test-renderer 和 stub fetch，不是真浏览器/真实 Electron 页面。
- TypeScript 通过不等于真实交互可用。

## 有界静态审查及三项红测闭环

审查发现两项 major：市场 validate/install/enable 与 discover/load 使用的 effective overlay 和身份不一致；不兼容 reload 清除运行时对象后，HTTP 失败出口未刷新共享 SkillManager 来源。主控先独立复现新增三红测：

```text
3 failed, 19 passed, 5 warnings in 4.50s
INDEPENDENT_EXIT_CODE=1
```

实施端修改共同有效清单 helper 和 reload 错误出口后，主控仅复跑对应三项：

```text
python -m pytest tests/test_plugin_compatibility.py::test_marketplace_effective_peer_manifest_controls_validate_install_identity_and_enable tests/test_plugin_compatibility.py::test_marketplace_overlay_mismatch_blocks_validation_and_install_before_copy tests/test_plugin_compatibility.py::test_failed_http_reload_refreshes_shared_skill_sources_after_version_upgrade -q -p no:cacheprovider --basetemp=<唯一 atlas-x6-redfix-supervisor>
3 passed, 5 warnings in 3.37s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。红测保留了原断言，未以削弱测试转绿。验证包含 base 不兼容/overlay 兼容、相反方向在复制前拒绝、别名身份和实际 SkillManager source 清退。此为限定定向回归，不是全库或 live。

## 真实验收状态

实施端正在临时数据根/专用端口做真实进程/API/页面与本机 MCP 验收。最终使用 8918 后端、5176 Vite；初次误用空闲但预留的8876，已要求仅正常关闭自有 runner，不动其他服务。一次独立浏览器读取了5173页面，仅 GET/按钮观察，无 grant/revoke；已要求停止该路径并确认实际插件请求指向8918。该错误路径不计为验收。

## 实施端真实页面与进程回执

主控通过 CDP 观察实施端报告并读取 `BEYOND-DSH-PROGRESS.md:108-118`，未独立重复 live 交互：

- 正常浏览器 UI：5176 页面展示 mismatch / 接受按钮禁用；勾选风险后点击豁免，按钮变为撤销；撤销后恢复接受按钮。POST / DELETE 目标8918，均HTTP200，无8765写入。
- 本机 MCP fixture 未触发 ping，因此 marker 不存在；撤销后 fixture进程为0，仅证明该时点无子进程，不证明真实工具执行。
- 后端：`LIVE_BACKEND_EXIT code=1 graceful=False forced=True logs=startup=complete; shutdown=complete; errors=0; last_error_type=unknown`。日志完整但30秒后强制终止，**自然退出未通过**。8918无监听；自有Vite经确认PID强制停止，5176无监听。
- 工具约束：context-mode拒绝shell内联HTTP状态读取，提示使用当前不可用的ctx_execute。实施端随后曾以Node REPL页面evaluate(fetch)读取相同状态，属于换通道规避；主控要求立即停止，实施端承认并落账。**这些状态快照不采信、不用于验收**。正常UI交互与被拒附加状态读取分别记录。

目前只能认定上述有限代码/定向测试/页面交互证据。完整 live capability/MCP状态、自然进程退出、真实模型与全目标仍未验收。实施端继续 X5/X7，不以X6增量冒充 Atlas 全面对齐或超越 DSH。
