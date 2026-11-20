# PAR-10 · T6-4 任务书 · 旧 Excel `.xls` 只读预览

## 选行与依据

- QUEUE 行:`F03-web` / `B-F03-PREVIEW-09`;已证实缺口 `.xls` 不在 accepted set、无解析路径(T6-1 只覆盖 docx/pptx;xlsx/csv/tsv 已有)。
- 依据:`PAR10-READY-NEXT.md` §旧 Excel .xls;`evidence/exec06-preview-office-20261118.txt`;T6-1 源树 `D:\Atlas\.worktrees\zcode-par10-office-fallback`。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-legacy-xls-preview`
- 分支 `zcode/par10-legacy-xls-preview`,HEAD `060071ab`。
- 先确认 T6-1 写者已停,把 T6-1 的 `office.py` 改动与测试作为基线移入(记录 sha256),再补 `.xls`;本树独占。

## 任务

1. 核对官方 `.xls` 路径与现有依赖/发布打包路径/前端文件分流;只写本树路由、worker、依赖与测试。
2. 在正式 HTTP 预览入口或常规工作区右栏打开临时真实 BIFF `.xls` 样本,验证多工作表、文本/数字/日期;损坏/加密文件给出清楚错误。
3. 保持 XLSX/CSV/TSV 工作;依赖缺失时给产品提示;沿用现有隔离/输入限制;明确实际支持格式。
4. 若本机缺可合法打包的 `.xls` 解析器,交付可重现依赖边界与最小继续差异,状态 `PARTIAL`/`BLOCKED`;不得用真实用户文件。
5. 测试 `@pytest.mark.unit`,命令/退出码/通过数完整记录。

## 验收

- 真实 `.xls` 经入口返回非空 HTML/表格或明确错误;损坏/加密不 500;xlsx/csv/tsv 不回归。
- 回执 `evidence/par10-t6-4.md`,末行 `PAR10_RECEIPT T6-4 READY|PARTIAL|BLOCKED`。