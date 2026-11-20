# PAR-10 · T6-1 任务书 · Office 预览依赖降级

## 选行与依据

- QUEUE 行:`F03-web`(03 Web/渲染层),能力 `B-F03-PREVIEW-08`。
- 已证实缺口:`evidence/exec06-preview-office-20261118.txt` §B——xlsx 真实链路可用;docx/pptx 代码链路完整但当前运行时缺 `python-docx`/`python-pptx`,`ModuleNotFoundError` 直接冒出;`.doc/.ppt` 仅 415。
- 目标不是安装依赖,而是让产品在依赖缺失时仍能安全预览 docx/pptx 的正文/幻灯片文本,并提供明确失败语义。

## 实际入口

- HTTP:`core/atlas/api/workspace_router.py:646` `GET /api/workspace/preview?root&path`。
- 隔离渲染:`core/atlas/office.py:29` `render_isolated_preview` → 子进程 `core/scripts/isolated_preview_worker.py` → `core/atlas/office.py:224` `render_office`。
- 前端:`frontend/src/renderer/shell/panels/FilesPanel.tsx:663-667` office iframe。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-office-fallback`
- 分支 `zcode/par10-office-fallback`,基线 HEAD `060071ab`。
- 只改本树与 `evidence/par10-t6-1.md`;主工作区只读;不 commit/push/merge/stash。

## 交付

1. 在 `core/atlas/office.py` 增加无第三方依赖的 OOXML 降级:
   - docx: `zipfile` + XML 解析 `word/document.xml`,输出段落/标题/表格文本的 HTML;
   - pptx: 解析 `ppt/slides/slideN.xml`(按序号),输出每页文本;
   - 优先保留 python-docx/python-pptx 现有路径;仅在 `ImportError`/依赖缺失时降级;
   - 限制 zip 成员数量/解压总量/文本长度,防止 zip bomb;不读取包外路径;
   - `.doc/.ppt/.xls` 仍不在 accepted set,返回既有 415 语义,不假装支持。
2. 依赖缺失且降级也失败时,返回结构化 `dependency_missing`/`unsupported` 错误(不把 `ModuleNotFoundError` 泄漏成 500)。
3. 测试(新增 `core/tests/test_office_preview_fallback.py`,全部 `@pytest.mark.unit`):
   - 用 `zipfile` 构造合法 docx/pptx 临时文件,经**实际 HTTP 路由**预览,断言 HTML 含正文/标题/表格/幻灯片文本;
   - 模拟 `docx`/`pptx` 不可导入,验证降级生效;
   - xlsx 既有路径不回归;`.doc`/`.ppt` 415;超大文件 413;非预期 zip 成员被拒绝;
   - 隔离 worker 端到端或等效真实入口证据。
4. 命令:`pytest ... --basetemp=<worktree>/.tmp/... -p no:cacheprovider`;记录解释器/版本、完整命令、退出码、通过数。ruff 改动文件。

## 验收

- 未安装 python-docx/python-pptx 时,`GET /api/workspace/preview` 对合法 docx/pptx 返回非空 HTML(含可读文本),不再 500。
- xlsx 保持既有行为;legacy `.doc/.ppt/.xls` 明确 415;路径/大小边界不放松。
- 回执末行:`PAR10_RECEIPT T6-1 READY|PARTIAL|BLOCKED`。