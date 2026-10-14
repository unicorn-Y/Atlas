# Atlas 记忆库 W0 执行结果

日期：2026-10-15  
工作区：`D:\atlas-mem-w0`，分支 `memory-w0`，基线 `1ec4b95fa8ed602e6cb2dba8189750b4dfebbdfe`。实现提交：`b43c0c5`。

## 各节执行摘要

0. 在既有工作区执行，未创建新 worktree；所有代码和测试只改任务书允许的 9 个文件，Python 使用 `D:\Atlas\core\.venv\Scripts\python.exe`。
1. 手改带 key 的条目时同步更新 `value`；提炼已编辑条目时以 `text` 作为当前值。
2. 新增过期判断，recall、人物/事情线索和普通搜索会隐藏过期项；历史搜索保留它们并标记 `expired`。
3. 常驻区分两遍分配，每个类别优先获得 400 字预算；现状条目先按到期时间排序。
4. 相关记忆搜索在打分和截断前排除常驻页、线索命中页，并传入统一的本地时间。
5. 忘记流程会擦除日记、当前数据和 Git 历史对象及提交信息；保留 tombstone 防止重新记入，变动视图过滤遗忘文本，撤销会拒绝恢复遗忘内容。忘记 API 和前端提示改为返回并展示后端报告。
6. 后台轮次先写入 SQLite 队列，重启后可补跑；日记阶段可续跑而不重复写入，按创建时间提炼，失败三次的行保留并计入 `pending_failed`。
7. 新增 `stance` 提示和解析；`set`、`alias` 只接受 `said`，撤回和忘记照常处理。
8. 未改“防回流”逻辑；沿用任务书结论，提炼事实仍以用户原话中的有效引文为准。
9. 新增任务书列出的 9 个场景并执行检查，详细结果见下文。
10. 实现提交 `b43c0c5` 和结果提交 `b6252e5` 已推送至 `origin/memory-w0`；首轮推送后本地和远端均为 `b6252e5a15e640432a69cd45365f6783f200bfbd`。本结果文件的最终修订已提交在 `memory-w0` 分支。

## 9.1 测试结果

专用测试使用 Atlas 后端虚拟环境。为避开 Windows 共享 pytest 临时目录清理的权限错误，运行时额外指定了工作区内的 `--basetemp`，测试结束后已清理该临时目录。

### `tests/test_memory_library_w0.py`

以下为终端输出原文：

```text
2026-10-15 02:46:12 [info     ] config.loaded                  path=C:\Users\25011\AppData\Local\Temp\atlas-tests-8yh_jl59\atlas\config\atlas.toml
.........                                                                [100%]
============================== warnings summary ===============================
tests/test_memory_library_w0.py::test_m01_edited_keyed_value_is_replaced_and_old_text_moves_to_history
  D:\atlas-mem-w0\core\atlas\api\settings_export_router.py:44: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class SettingsDocument(BaseModel):

tests/test_memory_library_w0.py::test_m01_edited_keyed_value_is_replaced_and_old_text_moves_to_history
  D:\atlas-mem-w0\core\atlas\api\settings_export_router.py:54: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class ImportPreviewRequest(BaseModel):

tests/test_memory_library_w0.py::test_m01_edited_keyed_value_is_replaced_and_old_text_moves_to_history
  D:\atlas-mem-w0\core\atlas\api\settings_export_router.py:61: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class ImportApplyRequest(BaseModel):

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
9 passed, 3 warnings in 12.47s
```

### Existing memory test selection

`python -m pytest tests -q -x -k memory --tb=short --basetemp D:\atlas-mem-w0\.pytest-temp-memory-final` reached 36 passing tests, then stopped at the unchanged model-router test below. Its isolated rerun failed the same way with `anthropic.InternalServerError: Error code: 502` from the fake Anthropic HTTP endpoint. This prevents claiming that the full existing memory selection passed; the failure path is in `atlas/models/router.py` and the provider transport, outside this task’s edited files.

以下为该运行的原始输出关键段：

```text
.................
...................
F
================================== FAILURES ==================================
_ test_native_anthropic_route_completes_over_fake_http_endpoint[memory_library] _
tests\test_model_router.py:149: in test_native_anthropic_route_completes_over_fake_http_endpoint
E   anthropic.InternalServerError: Error code: 502
=========================== short test summary info ===========================
FAILED tests/test_model_router.py::test_native_anthropic_route_completes_over_fake_http_endpoint[memory_library]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 36 passed, 2295 deselected, 3 warnings in 27.61s
```

### Frontend TypeScript

任务书命令 `npx tsc --noEmit -p .` 无法执行：`frontend` 没有本地 TypeScript 编译器，且没有默认 `tsconfig.json`。按允许方式临时将 `frontend/node_modules` junction 指向 `D:\Atlas\frontend\node_modules` 后，仍缺 TypeScript、React、`lucide-react` 等依赖；该 junction 已用 `cmd /c rmdir D:\atlas-mem-w0\frontend\node_modules` 移除。

另用 `D:\Atlas\node_modules\.bin\tsc.cmd` 检查项目实际的 `tsconfig.renderer.json` 和 `tsconfig.electron.json`，两者都因 W0 前端依赖缺失产生大量模块和 JSX 类型错误。筛查本次修改的 toast 行未发现该行诊断，但依赖不全，无法据此确认完整前端类型检查通过或证明没有新增错误。

## 9.2 真实模型冒烟

未运行。该项是可选验收，本次未启动任务书所述交互式计划任务和真实模型凭据流程。

## 未完成或与任务书不一致之处

- Python 用例全通过；既有筛选集有一项 fake HTTP 502，且单独重跑仍失败，原因和代码边界见上文。
- 前端完整类型检查受缺少依赖和默认配置文件阻塞；任务要求的 `npx tsc --noEmit -p .` 在当前工作区不可用。
- 真实模型冒烟未执行，因为它是可选项且需要交互式凭据流程。
- 为让忘记后 Git 新仓库的索引及 Windows 字节级检查可用，记忆库 Git 操作固定 `core.autocrlf=false`，并在历史替换后重建索引；这属于任务书 Windows 处理要求的实现细节。

