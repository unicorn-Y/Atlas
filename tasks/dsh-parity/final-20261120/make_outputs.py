# -*- coding: utf-8 -*-
"""Produce annexes, Excel workbook and README for the 2026-11-20 parity deliverable."""
import csv, io, json, os, collections, re

OUT = r"D:\Atlas\tasks\dsh-parity\final-20261120"
MAIN = os.path.join(OUT, "Atlas-DSH-完整对照表-20261120.tsv")
ATOMIC = r"D:\Atlas\tasks\dsh-parity\atomic\atomic-capabilities.jsonl"
EDGES = r"D:\Atlas\tasks\dsh-parity\atomic\interaction-edges.jsonl"


def read_tsv(p):
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return [dict(x) for x in csv.DictReader(f, delimiter="\t")]


def write_tsv(p, rows, cols=None):
    cols = cols or list(rows[0].keys())
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, delimiter="\t", fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


main = read_tsv(MAIN)
atomic = [json.loads(l) for l in io.open(ATOMIC, encoding="utf-8") if l.strip()]
edges = [json.loads(l) for l in io.open(EDGES, encoding="utf-8") if l.strip()]

COMP_MAP = {
    "@deepseek-ai/dsh-terminal-bash": "ATOM-TERMINAL-BASH",
    "@deepseek-ai/dsh-client-ui-schedule": "ATOM-UI-SCHEDULE",
    "@deepseek-ai/dsh-client-ui-schedule tests": "ATOM-UI-SCHEDULE",
    "@deepseek-ai/dsh-tool-terminal": "ATOM-TOOL-TERMINAL",
    "@deepseek-ai/dsh-terminal": "ATOM-TOOL-TERMINAL",
    "@deepseek-ai/dsh-tool-terminal -> @deepseek-ai/dsh-terminal -> client/ui-tool": "ATOM-TOOL-TERMINAL",
    "@deepseek-ai/dsh-api-session-controller": "ATOM-SESSION-CONTROLLER",
}
atom_rows = []
for a in atomic:
    comp = a.get("component", "")
    ev = a.get("evidence", "")
    if isinstance(ev, (dict, list)):
        ev = json.dumps(ev, ensure_ascii=False)
    units = a.get("source_units", []) or []
    atom_rows.append({
        "原子ID": a.get("atomic_id", ""),
        "历史状态": a.get("status", ""),
        "实施状态": a.get("implementation_status", ""),
        "组件": comp,
        "能力": a.get("capability", ""),
        "源码单元数": len(units),
        "源码单元样例": ";".join(str(x) for x in units[:5]),
        "开放义务": len(a.get("open_obligations", []) or []),
        "历史证据": str(ev)[:600],
        "对应主表ID": COMP_MAP.get(comp, "ATOM-MISC"),
    })
write_tsv(os.path.join(OUT, "Atlas-DSH-历史原子台账-476.tsv"), atom_rows)

edge_rows = []
for e in edges:
    row = {}
    for k, v in e.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        row[k] = str(v)[:800]
    edge_rows.append(row)
if edge_rows:
    write_tsv(os.path.join(OUT, "Atlas-DSH-历史交互链-218.tsv"), edge_rows)

# priority-split work lists
core = [r for r in main if r["优先级"] in ("P0", "P1")]
p2 = [r for r in main if r["优先级"] == "P2"]
write_tsv(os.path.join(OUT, "Atlas-DSH-施工单-核心-P0P1.tsv"), core)
write_tsv(os.path.join(OUT, "Atlas-DSH-施工单-P2.tsv"), p2)

# same-topic verdict conflicts
def _norm(s):
    s = re.sub(r"[\s\"'“”()（）:：,，。;；/\-]", "", s or "")
    return s[:36]
_g = collections.defaultdict(list)
for r in main:
    _g[(_norm(r["域编码"]), _norm(r["细节"]))].append(r)
_conf = [(k, v) for k, v in _g.items() if len(v) > 1 and len({x["结论"] for x in v}) > 1]
conf_rows = []
for (code, key), v in _conf:
    for x in v:
        conf_rows.append({"域编码": code, "同题键": key, "ID": x["ID"], "结论": x["结论"],
                          "细节": x["细节"], "Atlas证据": x["Atlas证据"], "差异或边界": x["差异或边界"][:300]})
if conf_rows:
    write_tsv(os.path.join(OUT, "Atlas-DSH-结论冲突-需裁决.tsv"), conf_rows)

# summary stats
status = collections.Counter(r["结论"] for r in main)
prio = collections.Counter(r["优先级"] for r in main)
evchk = collections.Counter(r["证据校验"] for r in main)
domain = collections.Counter(r["域编码"] for r in main)

stats = []
stats.append(("生成日期", "2026-11-20"))
stats.append(("DSH 基线", "master 2e39e704（最新，2026-11-18T18:58:42+08:00）；发布 rc.5 9c2670d3"))
stats.append(("Atlas 基线", "wave3 HEAD 060071ab（2026-11-15）+ 工作区未提交改动"))
stats.append(("主表行数", len(main)))
stats.append(("DSH 工作区覆盖", "397/397（packages 391 + apps 6）"))
stats.append(("DSH 有专项行的工作区", "185"))
stats.append(("历史原子台账", len(atomic)))
stats.append(("历史交互链", len(edges)))
for k, v in status.most_common():
    stats.append((f"结论 · {k}", v))
for k, v in prio.most_common():
    stats.append((f"优先级 · {k or '无动作'}", v))
for k, v in evchk.most_common():
    stats.append((f"证据校验 · {k}", v))
for k in ["F01", "F02", "F03", "F04", "F05", "F06", "F07", "F08", "F09", "F10", "X", "T"]:
    stats.append((f"域 · {k}", domain.get(k, 0)))

with io.open(os.path.join(OUT, "Atlas-DSH-统计-20261120.tsv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t"); w.writerow(["指标", "数值"]); w.writerows(stats)

# domain x verdict matrix
_domains = ["F01","F02","F03","F04","F05","F06","F07","F08","F09","F10","X","T"]
_verdicts = ["缺失","部分","候选对应","未核","设计差异","已对齐","Atlas独有","非产品面"]
mat = []
for d in _domains:
    sub = [r for r in main if r["域编码"] == d]
    row = {"域编码": d, "合计": len(sub)}
    for v in _verdicts: row[v] = sum(1 for r in sub if r["结论"] == v)
    mat.append(row)
mat.append({"域编码": "合计", "合计": len(main), **{v: sum(1 for r in main if r["结论"] == v) for v in _verdicts}})
write_tsv(os.path.join(OUT, "Atlas-DSH-域汇总-20261120.tsv"), mat)

# Excel workbook
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active; ws.title = "总表"
cols = list(main[0].keys())
ws.append(cols)
for r in main:
    ws.append([r.get(c, "") for c in cols])
for c in ws[1]:
    c.font = Font(bold=True); c.alignment = Alignment(vertical="top", wrap_text=True)
ws.freeze_panes = "A2"
ws.auto_filter.ref = ws.dimensions
widths = {"ID": 28, "领域": 18, "细节": 42, "DSH行为": 60, "DSH证据": 50, "Atlas行为": 55,
          "Atlas证据": 48, "差异或边界": 55, "Atlas行动": 50, "来源": 26}
for i, c in enumerate(cols, 1):
    ws.column_dimensions[get_column_letter(i)].width = widths.get(c, 12)
for row in ws.iter_rows(min_row=2):
    for c in row:
        c.alignment = Alignment(vertical="top", wrap_text=True)

ws2 = wb.create_sheet("施工单")
acts = [r for r in main if r["结论"] in ("缺失", "部分", "候选对应", "未核")]
act_cols = ["ID", "域编码", "领域", "细节", "结论", "优先级", "Atlas行动", "Atlas证据", "差异或边界"]
ws2.append(act_cols)
for r in acts:
    ws2.append([r.get(c, "") for c in act_cols])
for c in ws2[1]:
    c.font = Font(bold=True)
ws2.freeze_panes = "A2"; ws2.auto_filter.ref = ws2.dimensions
for i, c in enumerate(act_cols, 1):
    ws2.column_dimensions[get_column_letter(i)].width = {"ID": 28, "细节": 42, "Atlas行动": 55, "差异或边界": 55}.get(c, 14)
for row in ws2.iter_rows(min_row=2):
    for c in row: c.alignment = Alignment(vertical="top", wrap_text=True)

ws3 = wb.create_sheet("覆盖台账")
ledger = read_tsv(os.path.join(OUT, "Atlas-DSH-覆盖台账.tsv"))
lcols = list(ledger[0].keys())
ws3.append(lcols)
for r in ledger: ws3.append([r.get(c, "") for c in lcols])
for c in ws3[1]: c.font = Font(bold=True)
ws3.freeze_panes = "A2"; ws3.auto_filter.ref = ws3.dimensions
for i, c in enumerate(lcols, 1):
    ws3.column_dimensions[get_column_letter(i)].width = {"包清单": 52, "包名": 44, "说明": 60, "行ID": 40}.get(c, 12)

ws4 = wb.create_sheet("历史原子")
acols = list(atom_rows[0].keys())
ws4.append(acols)
for r in atom_rows: ws4.append([r.get(c, "") for c in acols])
for c in ws4[1]: c.font = Font(bold=True)
ws4.freeze_panes = "A2"; ws4.auto_filter.ref = ws4.dimensions
for i, c in enumerate(acols, 1):
    ws4.column_dimensions[get_column_letter(i)].width = {"能力": 70, "历史证据": 60, "组件": 40, "源码单元样例": 40}.get(c, 12)

ws5 = wb.create_sheet("统计")
ws5.append(["指标", "数值"])
for k, v in stats: ws5.append([k, v])
for c in ws5[1]: c.font = Font(bold=True)
ws5.column_dimensions["A"].width = 40; ws5.column_dimensions["B"].width = 90

wb.save(os.path.join(OUT, "Atlas-DSH-完整对照表-20261120.xlsx"))
print("annexes + xlsx written")

# README
readme = f"""# Atlas × DSH 完整对照表（2026-11-20 接手版）

这是 Codex 会话「全面拆解最新版DSH」在 2026-11-20 07:34 因额度耗尽中断后，由 ZCode 接手续建的**唯一主表**与配套证据。

## 1. 基线（“最新”指什么）

| 侧 | 基线 | 说明 |
|---|---|---|
| DSH | `master` = `2e39e704` | 2026-11-18 18:58 +08:00；已用 `git ls-remote` 复查，截至 2026-11-20 仍是上游最新 |
| DSH 发布 | `dsh-v0.2.2-rc.5` = `9c2670d3` | 当前最新 release tag；表内用「DSH版本」列区分 rc.5 与 master 新增 |
| Atlas | `wave3` HEAD = `060071ab` | 2026-11-15；另加工作区未提交改动（Atlas 侧证据按工作区文件核对） |

DSH 证据库：`D:\\Atlas\\.worktrees\\_codex-dsh-rc5-source.git`（只读裸库）。
Atlas 侧：`D:\\Atlas` 工作区。

## 2. 交付物

| 文件 | 内容 | 行数 |
|---|---|---|
| **Atlas-DSH-完整对照表-20261120.tsv / .xlsx** | 主表：逐条能力对比 | {len(main)} |
| Atlas-DSH-施工单-20261120.tsv / .xlsx「施工单」 | 缺失/部分/候选/未核，按域和优先级排序 | {len(acts)} |
| **Atlas-DSH-施工单-核心-P0P1.tsv** | 只含 P0/P1，真正建议先做的清单 | {len(core)} |
| Atlas-DSH-覆盖台账.tsv | 397 个 DSH 工作区逐个对账，证明无静默遗漏 | 397 |
| Atlas-DSH-历史原子台账-476.tsv | Atlas 原有原子能力台账（历史口径，未回填当前状态） | {len(atomic)} |
| Atlas-DSH-历史交互链-218.tsv | Atlas 原有交互链台账 | {len(edges)} |
| Atlas-DSH-统计-20261120.tsv | 全部计数 | {len(stats)} |
| Atlas-DSH-域汇总-20261120.tsv | 12 个域 × 8 种结论的交叉计数 | 13 |

## 3. 列口径

- **结论**：`缺失`（DSH 有、Atlas 未定位到等价实现） / `部分`（Atlas 有但不完整） / `候选对应`（本次静态定位到 Atlas 实现，未做行为核验） / `未核`（证据只够记录单侧事实或明确标了待核） / `设计差异`（两侧都有，机制/形态不同） / `已对齐`（历史台账判定等价） / `Atlas独有` / `非产品面`（测试基座等）。
- **优先级**：施工启发式，不是产品决策。`P0` 只给安全/权限类且 Atlas 明确缺失的 3 条；DSH 专有的 CLI/IPC 传输细节降为 P2/P3。
- **证据校验**：对每行证据里出现的仓库相对路径做存在性校验（DSH 对 `2e39e704`，Atlas 对工作区）。`DSH 路径失配` / `Atlas 路径失配` 的行需要人工复核证据路径；`无 DSH 路径` 常见于 Atlas 单侧行。
- **证据等级**：`源码静态`（读源码/清单）/ `历史台账（含源码锚点）` / `清单级`（仅 package.json 元数据）。
- **DSH版本**：`rc.5` 或 `master 新增`，用于区分已发布与开发中变化。

## 4. 这次补齐了什么

Codex 中断时留下 23 张表、去重后 1,064 条，但：
- DSH 397 个工作区里只有 218 个被行引用过；
- 151 个包没有任何行为行；
- Atlas 自己的 476 条原子台账和 218 条交互链完全没进表（ID 体系不同，零重叠）。

本次补了：
- 167 个包的专项行（151 个未覆盖包 + 16 个仅被字面提及的包），每条给 DSH 清单/入口与 Atlas 候选锚点；
- 5 条原子台账组件汇总行，并把 476+218 条历史台账作为附件保留；
- 统一结论/优先级/证据校验口径，去重后 **{len(main)} 行，{len(set(r["ID"] for r in main))} 个唯一 ID**；
- 397/397 工作区全部有行，零遗漏（覆盖台账逐项可查）。

## 4.1 结论冲突（施工前需裁决）

共 {len(_conf)} 组同题行结论不一致（全部在 F04 SDK/CLI 面）。它们同时保留在表内，未强行合并；详见 `Atlas-DSH-结论冲突-需裁决.tsv`。出现冲突时不要直接按某一行开工，先回查两侧源码。

## 5. 必须说清的边界

1. **这是静态源码级对照，不是运行时实测。** 标注 `源码静态` 的行都没有启动两侧产品、没有真实模型/账号/安装器操作。
2. **`候选对应` 不等于“已对齐”。** 它只表示在 Atlas 工作区定位到了同域实现，具体参数、默认值、错误分支仍需按行核。
3. **历史原子台账是旧口径。** 476 条里 470 条为 `PARTIAL`，是 2026-11-15 前后的状态，未回填今天；不要把它当今日剩余工作量。
4. **证据路径存在性校验**：{evchk.get('DSH 路径存在；Atlas 路径存在',0)} 行两侧路径都命中；{evchk.get('DSH 路径存在；无 Atlas 路径',0)} 行只有 DSH 路径（单侧行）；{evchk.get('无 DSH 路径；Atlas 路径存在',0)} 行只有 Atlas 路径；{sum(v for k,v in evchk.items() if '失配' in k)} 行存在路径失配，需要按「证据校验」列复核。
5. **DSH 专有传输/CLI 细节**（如 `dsh --profile`、desktop IPC 通道名）在表里标为缺失，但优先级降为 P2/P3；它们不代表 Atlas 产品能力缺口，只代表协议不兼容。

## 6. 怎么用它给 Atlas 加东西

1. 打开 Excel「施工单」，先看 `P0`（3 条，安全/权限类）和 `P1`。
2. 按「域编码」筛：F05 内核、F06 模型/上下文、F07 会话、F08 工具/执行、F09 扩展/权限 是主要施工区。
3. 每行读三列：`DSH行为`（要做成什么）、`Atlas证据`（从哪改）、`Atlas行动`（具体动作）。
4. `候选对应` 行先做行为核验，不要直接重写；`部分` 行按 `差异或边界` 补缺口；`缺失` 行才考虑新增模块。
5. 历史原子台账用于追溯细粒度义务，不用于排期。

## 7. 与旧表的关系

Codex 的 34 张原始表仍在 `C:\\Users\\25011\\Documents\\codex\\2026-11-19\\kan\\outputs\\`，本表是其去重、补全、统一口径后的主表。旧表继续作为证据附件使用；发生冲突时以本表 + 「证据校验」为准，并回查原始 Git 路径。
"""
io.open(os.path.join(OUT, "README-20261120.md"), "w", encoding="utf-8", newline="\n").write(readme)
print("README written")