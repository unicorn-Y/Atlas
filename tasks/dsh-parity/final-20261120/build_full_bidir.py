# -*- coding: utf-8 -*-
"""Bidirectional full inventory from Codex's declaration tables.

Inputs (Codex session, authoritative):
  Atlas-DSH-最新TS到JS语法声明.tsv   91,002 declarations
  Atlas-DSH-最新Python语法声明.tsv   19,531 declarations
Outputs:
  Atlas-DSH-双向全量对照表-20261120.tsv
  Atlas-DSH-缺口簇-按包-20261120.tsv
  Atlas-DSH-全量统计-20261120.tsv
"""
import csv, io, os, re, json, collections

BASE = r"C:\Users\25011\Documents\codex\2026-11-19\kan\outputs"
OUT = r"D:\Atlas\tasks\dsh-parity\final-20261120"
MAIN = os.path.join(OUT, "Atlas-DSH-完整对照表-20261120.tsv")
INV = r"D:\Atlas\tasks\dsh-parity\_dsh_pkg_inventory.tsv"

BEHAVIOR = {"函数", "function", "async function", "方法", "Constructor", "class", "ClassDeclaration",
            "decorator route", "Registration/call", "GetAccessor", "SetAccessor"}
DATA = {"Module variable", "module binding", "属性", "annotation", "EnumMember"}
TYPE = {"接口", "属性签名", "类型别名", "方法签名", "Export assignment", "模块", "EnumDeclaration",
        "CallSignature", "ConstructSignature", "IndexSignature"}
STOP = set("get set run start stop close open init constructor apply inject name value data config state type "
           "create update delete load save read write handle list item items options result error is has can on to "
           "from with for and the this self cls args kwargs".split())


def rows(p):
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return [dict(x) for x in csv.DictReader(f, delimiter="\t")]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def toks(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s or "")
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)
    return {t.lower() for t in s.split() if len(t) > 2 and t.lower() not in STOP}


def layer_of(p):
    if re.search(r"(^|/)(tests?|__tests__|test-support)(/|$)|\.(test|spec)\.", p):
        return "测试基座"
    if re.match(r"^(packages/[^/]+/[^/]+/src/|apps/[^/]+/src/|core/atlas/|frontend/src/|backend-adapter/src/)", p):
        return "产品运行面"
    if re.search(r"(^|/)(scripts|packaging|\.github)/", p):
        return "构建发布面"
    return "其他"


def is_type(p):
    return bool(re.match(r"^(packages/[^/]+/[^/]+/src/|apps/[^/]+/src/|core/atlas/|frontend/src/|backend-adapter/src/)", p))


def domain_of(path):
    m = re.match(r"packages/([^/]+)/", path)
    g = m.group(1) if m else ("apps" if path.startswith("apps/") else "")
    if path.startswith("core/atlas/"):
        mod = path.split("/")[2] if len(path.split("/")) > 2 else ""
        return {
            "agent": "F05", "engine": "F05", "runtime": "F05", "workflow": "F05", "scheduler": "F05",
            "api": "F04", "cli.py": "F04", "server.py": "F04", "gateway_service": "F04",
            "models": "F06", "memory": "F07", "session_s": "F07", "session_archive": "F07",
            "engine_state": "F07", "tools": "F08", "sandbox": "F08", "ssh": "F08", "office": "F08",
            "plugins": "F09", "skills": "F09", "approval_policy": "F09", "approval_outcome": "F09",
            "telemetry": "F10", "devices": "F02", "channels": "F10", "projects": "F10",
            "memory_": "F07", "library": "F07", "library_": "F07", "research": "F07",
        }.get(mod, "F05")
    mp = {
        "client": "F03", "llm": "F06", "account": "F06", "context": "F06", "credentials": "F06",
        "session": "F07", "session-query": "F07", "storage": "F07", "spill": "F07", "feedback": "F07",
        "attachment": "F07", "shell": "F08", "fs": "F08", "ssh": "F08", "terminal": "F08",
        "subprocess": "F08", "sandbox": "F08", "web": "F08", "jobs": "F08", "document": "F08",
        "api": "F04", "acp": "F04", "typert": "F04", "interaction": "F05", "plan": "F05", "goal": "F05",
        "todo": "F05", "guard": "F05", "subagent": "F05", "workflow": "F05", "core": "F05",
        "boot": "F01", "bundle": "F01", "host": "F02", "computer-use": "F02", "apps": "F02",
        "plugin": "F09", "connector": "F09", "extensions": "F09", "skill": "F09", "mcp": "F09",
        "settings": "F10", "identity": "F10", "team": "F10", "util": "X", "test-support": "T",
        "experimental": "F03", "preset": "F06", "credentials ": "F06",
    }
    return mp.get(g, "X")


def classify_kind(k):
    if k in BEHAVIOR:
        return "行为"
    if k in DATA:
        return "数据/配置"
    if k in TYPE:
        return "类型契约"
    if k == "annotation":
        return "数据/配置"
    return "其他"


def parse_entries(decl_cell):
    out = []
    for e in decl_cell.split(" ｜ "):
        e = e.strip()
        if not e:
            continue
        m = re.match(r"(\d+)\s+(\S+)\s*(.*)$", e)
        if not m:
            continue
        line = int(m.group(1)); k = m.group(2); rest = m.group(3).strip()
        # extract name
        if k in ("Module variable", "module binding", "Export assignment"):
            parts = rest.split(" ", 1)
        elif k in ("async function",):
            parts = rest.split(" ", 1)
        else:
            parts = rest.split(" ", 1)
        name = parts[0] if parts else ""
        sig = parts[1] if len(parts) > 1 else ""
        if k == "async function" and name == "function":
            p2 = sig.split(" ", 1); name = p2[0]; sig = p2[1] if len(p2) > 1 else ""
        if k == "Registration/call":
            name = rest.split(" ", 1)[0]
            sig = rest[len(name):].strip()
        if k == "decorator route":
            mm = re.match(r"(\S+)\s*(.*)$", rest)
            name = mm.group(1) if mm else rest; sig = mm.group(2) if mm else ""
        out.append({"line": line, "kind": k, "name": name, "sig": sig, "raw": e,
                    "cat": classify_kind(k)})
    return out


# ---- load declarations ----
items = []
for fname, product in [("Atlas-DSH-最新TS到JS语法声明.tsv", None), ("Atlas-DSH-最新Python语法声明.tsv", None)]:
    for r in rows(os.path.join(BASE, fname)):
        prod = "DSH" if r["来源"].startswith("DSH") else "Atlas"
        path = r["Git路径"]
        for d in parse_entries(r["逐条声明（行号、类型、名称与签名）"]):
            items.append({**d, "product": prod, "source": r["来源"], "file": path, "sha": r["对象SHA"],
                          "layer": layer_of(path), "domain": domain_of(path), "prod_path": is_type(path)})
print("declarations:", len(items), collections.Counter((i["product"], i["cat"]) for i in items))

# ---- package inventory and package verdict ----
inv = rows(INV)
main = rows(MAIN)
pkg_verdict = {}
for row in main:
    ev = row.get("DSH证据", "")
    for it in inv:
        d = os.path.dirname(it["manifest"])
        if d and d in ev:
            v = row["结论"]
            rank = {"缺失": 5, "部分": 4, "候选对应": 3, "未核": 2, "设计差异": 1, "已对齐": 0}
            if d not in pkg_verdict or rank.get(v, 2) > rank.get(pkg_verdict[d], 2):
                pkg_verdict[d] = v

# package -> Atlas candidate files/prefixes
pkg_files = collections.defaultdict(set)
pkg_prefix = collections.defaultdict(set)
EVPAT = re.compile(r"[A-Za-z0-9_@./-]+\.(?:tsx|ts|jsx|js|mjs|cjs|json|py|css|toml|yaml|yml|md)(?![A-Za-z0-9])")
def arel(p): return re.match(r"^(?:packages|apps|frontend|core|backend-adapter)/", p)
for row in main:
    ev = row.get("DSH证据", ""); ae = row.get("Atlas证据", "")
    dirs = [os.path.dirname(it["manifest"]) for it in inv if os.path.dirname(it["manifest"]) and os.path.dirname(it["manifest"]) in ev]
    afiles = [x for x in EVPAT.findall(ae or "") if arel(x)]
    for d in dirs:
        for p in afiles:
            if p.endswith("/") or "." not in p.rsplit("/", 1)[-1]:
                pkg_prefix[d].add(p)
            else:
                pkg_files[d].add(p)
# candidates2
c2 = os.path.join(OUT, "_atlas_candidates2.tsv")
if os.path.exists(c2):
    for r in rows(c2):
        d = os.path.dirname(r["manifest"])
        for m in re.finditer(r"([A-Za-z0-9_@./-]+\.(?:tsx|ts|js|py))\[", r["candidates"]):
            pkg_files[d].add(m.group(1))

# Atlas index
atlas = [i for i in items if i["product"] == "Atlas"]
atlas_by_full = collections.defaultdict(list)
atlas_by_last = collections.defaultdict(list)
atlas_by_file = collections.defaultdict(list)
token_idx = collections.defaultdict(list)
for idx, a in enumerate(atlas):
    n = norm(a["name"]); last = norm(a["name"].split(".")[-1])
    atlas_by_full[n].append(idx)
    atlas_by_last[last].append(idx)
    atlas_by_file[a["file"]].append(idx)
    for t in toks(a["name"]):
        token_idx[t].append(idx)
# package rows
pkg_rows = collections.defaultdict(set)
path_pkgs = collections.defaultdict(set)
for d, fs in pkg_files.items():
    for f in fs: path_pkgs[f].add(d)
for d, ps in pkg_prefix.items():
    for p in ps:
        for idx, a in enumerate(atlas):
            if a["file"].startswith(p):
                pkg_rows[d].add(idx)
for idx, a in enumerate(atlas):
    for d in path_pkgs.get(a["file"], ()):
        pkg_rows[d].add(idx)
print("atlas decls:", len(atlas), "packages mapped:", len(pkg_rows))

GENERIC = set("get set run start stop close open init constructor apply inject name value data config state "
              "type create update delete load save read write handle list item result error is has can on to from "
              "with for and the this self cls args kwargs main setup teardown test".split())


def cand_rows(pkg, parent=None, name=None):
    out = set(pkg_rows.get(pkg, ()))
    if parent:
        full = norm(parent + "." + name)
        out.update(atlas_by_full.get(full, ()))
        if name and norm(name) not in GENERIC:
            for j in atlas_by_last.get(norm(name), ())[:80]:
                if atlas[j]["name"].lower().startswith(parent.lower() + "."):
                    out.add(j)
    if name and len(name) >= 5 and norm(name) not in GENERIC:
        out.update(atlas_by_last.get(norm(name), ())[:80])
    return list(out)[:250]


def best_match(d):
    name = d["name"]; cat = d["cat"]
    m = re.match(r"((?:packages|apps)/[^/]+(?:/[^/]+)?)/", d["file"])
    pkg = m.group(1) if m else ""
    parent = name.split(".")[0] if "." in name else None
    last = name.split(".")[-1]
    cands = cand_rows(pkg, parent, last if parent else name)
    if not cands:
        cands = list(range(len(atlas)))[:0]
    best = None
    for j in cands:
        a = atlas[j]
        if cat == "类型契约" and a["cat"] != "类型契约" and not a["name"].split(".")[-1] == last:
            continue
        score = 0.0; how = ""
        nf, nlast = norm(name), norm(last)
        af, alast = norm(a["name"]), norm(a["name"].split(".")[-1])
        if nf and nf == af:
            score, how = 1.0, "全名精确"
        elif nlast == alast and len(nlast) >= 4 and nlast not in GENERIC:
            score, how = 0.92, "末名精确"
        elif nlast and alast and (nlast in af or af in nlast) and len(nlast) >= 6:
            score, how = 0.72, "名称包含"
        else:
            td, ta = toks(name), toks(a["name"])
            if td and ta:
                jac = len(td & ta) / len(td | ta)
                if jac >= 0.66: score, how = 0.68, "词重叠强"
                elif jac >= 0.5: score, how = 0.56, "词重叠中"
                elif jac >= 0.40: score, how = 0.46, "词重叠弱"
        if score and j in pkg_rows.get(pkg, ()):
            score += 0.08; how += "+包内"
        if score and a["cat"] == cat:
            score += 0.02
        if score > (best[0] if best else 0):
            best = (min(score, 1.0), how, j)
    return best


out = []
matched_atlas = set()
stats = collections.Counter()
for d in items:
    if d["product"] == "DSH":
        b = best_match(d)
        if b:
            score, how, j = b; a = atlas[j]; matched_atlas.add(j)
            v = "候选对应（高）" if score >= 0.9 else ("候选对应（中）" if score >= 0.65 else "候选对应（低）")
            status = "已定位"
            af, an, asig = a["file"], a["name"], a["raw"][:300]
        else:
            score = 0; how = ""; a = None; af = an = asig = ""
            pv = pkg_verdict.get(d["file"].rsplit("/", 1)[0], "")
            # nearest package dir verdict
            m = re.match(r"((?:packages|apps)/[^/]+(?:/[^/]+)?)/", d["file"])
            if m: pv = pkg_verdict.get(m.group(1), pv)
            if d["layer"] != "产品运行面":
                v = "不适用"
            elif d["cat"] == "类型契约":
                v = "未定位（类型契约）"
            elif d["cat"] == "数据/配置":
                v = "未定位（数据/配置）"
            elif pv == "缺失":
                v = "缺失"
            elif pv == "部分":
                v = "部分（包级）"
            elif pv == "候选对应":
                v = "未定位"
            elif pv == "已对齐":
                v = "未定位（包级已对齐）"
            else:
                v = "未核"
            status = "不适用" if v == "不适用" else "未开始"
        pkg_name = re.match(r"((?:packages|apps)/[^/]+(?:/[^/]+)?)/", d["file"])
        out.append({"ID": "", "侧": "DSH", "来源": d["source"], "域编码": d["domain"], "包/模块": pkg_name.group(1) if pkg_name else d["file"].split("/")[0], "层级": d["layer"], "类别": d["cat"], "文件": d["file"], "行": d["line"], "声明类型": d["kind"], "名称": d["name"], "签名/原文": d["raw"][:500], "对侧文件": af, "对侧名称": an, "对侧声明": asig, "匹配方式": how, "匹配分": f"{score:.2f}", "对照结论": v, "推进状态": status})
        stats[("DSH", v)] += 1

# Atlas-only rows
for j, a in enumerate(atlas):
    if j in matched_atlas: continue
    out.append({"ID": "", "侧": "Atlas", "来源": a["source"], "域编码": a["domain"], "包/模块": a["file"].split("/")[0] + "/" + (a["file"].split("/")[1] if len(a["file"].split("/")) > 1 else ""), "层级": a["layer"], "类别": a["cat"], "文件": a["file"], "行": a["line"], "声明类型": a["kind"], "名称": a["name"], "签名/原文": a["raw"][:500], "对侧文件": "", "对侧名称": "", "对侧声明": "", "匹配方式": "", "匹配分": "", "对照结论": "Atlas独有", "推进状态": "已存在" if a["layer"] == "产品运行面" else "不适用"})
    stats[("Atlas", "Atlas独有")] += 1

# IDs
counters = collections.Counter()
for r in out:
    base = f'{r["侧"]}-{r["域编码"]}-{re.sub(r"[^A-Za-z0-9]+", "-", r["文件"].rsplit("/", 1)[-1])}-{re.sub(r"[^A-Za-z0-9]+", "-", r["名称"])[:40]}'
    counters[base] += 1
    r["ID"] = base if counters[base] == 1 else f"{base}-{counters[base]}"

out.sort(key=lambda r: (r["域编码"], r["侧"], r["包/模块"], r["文件"], r["行"]))
COLS = ["ID", "侧", "来源", "域编码", "包/模块", "层级", "类别", "文件", "行", "声明类型", "名称", "签名/原文", "对侧文件", "对侧名称", "对侧声明", "匹配方式", "匹配分", "对照结论", "推进状态"]
with io.open(os.path.join(OUT, "Atlas-DSH-双向全量对照表-20261120.tsv"), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, delimiter="\t", fieldnames=COLS); w.writeheader(); w.writerows(out)

# gap clusters
clusters = collections.defaultdict(lambda: {"n": 0, "missing": 0, "partial": 0, "unloc": 0, "samples": []})
for r in out:
    if r["侧"] != "DSH" or r["层级"] != "产品运行面" or r["类别"] not in ("行为", "数据/配置"): continue
    if r["推进状态"] == "已定位": continue
    c = clusters[r["包/模块"]]
    c["n"] += 1
    if r["对照结论"] == "缺失": c["missing"] += 1
    elif r["对照结论"].startswith("部分"): c["partial"] += 1
    else: c["unloc"] += 1
    if len(c["samples"]) < 8: c["samples"].append(r["名称"] + "(" + r["声明类型"] + ")")
cl_rows = []
for pkg, c in clusters.items():
    code = domain_of(pkg)
    score = c["missing"] * 3 + c["partial"] * 2 + c["unloc"]
    prio = "P0" if re.search(r"sandbox|authorization|approval|credential|security", pkg, re.I) else ("P1" if code in ("F05", "F06", "F07", "F08", "F09") else "P2")
    cl_rows.append({"包/模块": pkg, "域编码": code, "优先级": prio, "未定位声明数": c["n"], "缺失": c["missing"], "部分包级": c["partial"], "其他未定位": c["unloc"], "权重": score, "样例": "; ".join(c["samples"])})
cl_rows.sort(key=lambda r: ({"P0": 0, "P1": 1, "P2": 2}[r["优先级"]], -r["权重"]))
with io.open(os.path.join(OUT, "Atlas-DSH-缺口簇-按包-20261120.tsv"), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, delimiter="\t", fieldnames=list(cl_rows[0].keys())); w.writeheader(); w.writerows(cl_rows)

st = [("声明总数", len(items)), ("DSH", sum(1 for i in items if i["product"] == "DSH")), ("Atlas", sum(1 for i in items if i["product"] == "Atlas")),
      ("DSH 行为", sum(1 for i in items if i["product"] == "DSH" and i["cat"] == "行为")),
      ("DSH 类型契约", sum(1 for i in items if i["product"] == "DSH" and i["cat"] == "类型契约")),
      ("DSH 数据/配置", sum(1 for i in items if i["product"] == "DSH" and i["cat"] == "数据/配置")),
      ("Atlas 行为", sum(1 for i in items if i["product"] == "Atlas" and i["cat"] == "行为")),
      ("输出行", len(out))]
for (side, v), n in stats.most_common(): st.append((f"{side} · {v}", n))
with io.open(os.path.join(OUT, "Atlas-DSH-全量统计-20261120.tsv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t"); w.writerow(["指标", "数值"]); w.writerows(st)
print(json.dumps({"decls": len(items), "out_rows": len(out), "clusters": len(cl_rows), "atlas_only": len(atlas) - len(matched_atlas)}, ensure_ascii=False))