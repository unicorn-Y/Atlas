"""Aggregate Atlas run logs into structure-only stats.

Never prints tool arguments, outputs, error text, prompts or reasons — only
model names, counts, durations, tool names (MCP collapsed to server) and
fixed-vocabulary codes.
"""
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,40}$")
STUCK_CODES = {"repeated_call_result", "repeated_errors", "monologue", "alternating_loop"}


def tool_label(name: str) -> str:
    name = str(name or "?")
    if "__" in name:
        return "mcp:" + name.split("__", 1)[0][:20]
    return name if IDENT.match(name) else "?"


def exc_type(reason) -> str:
    head = str(reason or "").split(":", 1)[0].strip()
    return head if IDENT.match(head) else "other"


runs = {}
for path in sorted(ROOT.glob("*/*.jsonl")):
    r = {"date": path.parent.name, "id": path.stem[:8], "model": "?", "kernel": "?",
         "status": "unfinished", "dur": None, "calls": 0, "model_err": Counter(),
         "tools": [], "tool_err": Counter(), "stuck": Counter(), "compact": 0,
         "repair": 0, "fail": "", "in_tok": 0, "out_tok": 0, "ws": None}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        continue
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ev = e.get("event")
        if ev == "run_start":
            r["model"] = str(e.get("model") or "?")[:40]
            r["kernel"] = str(e.get("kernel") or "?")[:10]
            r["ws"] = bool(e.get("workspace"))
        elif ev == "model_request" and "purpose" in e:
            if e.get("purpose") == "conversation":
                r["calls"] += 1
        elif ev == "model_error":
            cat = str(e.get("category") or "?")
            r["model_err"][cat if IDENT.match(cat) else "?"] += 1
        elif ev == "tool_start":
            r["tools"].append(tool_label(e.get("name")))
        elif ev == "tool_result":
            if e.get("is_error"):
                r["tool_err"][tool_label(e.get("name"))] += 1
        elif ev == "stuck":
            code = str(e.get("reason") or "")
            r["stuck"][code if code in STUCK_CODES else "other"] += 1
        elif ev == "compaction":
            r["compact"] += 1
        elif ev == "repair":
            r["repair"] += 1
        elif ev == "run_end":
            r["status"] = str(e.get("status") or "?")[:12]
            r["dur"] = e.get("duration_ms")
            r["in_tok"] = int(e.get("total_input_tokens") or 0)
            r["out_tok"] = int(e.get("total_output_tokens") or 0)
            if r["status"] == "failed":
                r["fail"] = exc_type(e.get("reason"))
    runs[path] = r


def streak(seq):
    best, cur, prev = 0, 0, None
    for x in seq:
        cur = cur + 1 if x == prev else 1
        prev = x
        best = max(best, cur)
    return best


def compact_seq(seq, limit=14):
    out, prev, n = [], None, 0
    for x in seq + [None]:
        if x == prev:
            n += 1
            continue
        if prev is not None:
            out.append(prev + (f"x{n}" if n > 1 else ""))
        prev, n = x, 1
    s = " > ".join(out[:limit])
    return s + (" > ..." if len(out) > limit else "")


R = list(runs.values())
dates = sorted({r["date"] for r in R})
print(f"runs: {len(R)}  dates: {dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}  days: {len(dates)}")
print("kernel:", dict(Counter(r["kernel"] for r in R)))
print("has workspace:", dict(Counter(r["ws"] for r in R)))
print()

by_model = defaultdict(list)
for r in R:
    by_model[r["model"]].append(r)
print("== per model")
print(f"{'model':38} {'runs':>5} {'ok':>4} {'fail':>4} {'intr':>4} {'unfin':>5} {'med_s':>6} {'p90_s':>6} {'med_calls':>9} {'med_tools':>9} {'tool_err%':>9} {'stuck':>5} {'streak3+':>8} {'med_in_k':>8}")
for model, rs in sorted(by_model.items(), key=lambda kv: -len(kv[1])):
    durs = sorted(r["dur"] / 1000 for r in rs if isinstance(r["dur"], (int, float)))
    tools = sum(len(r["tools"]) for r in rs)
    terr = sum(sum(r["tool_err"].values()) for r in rs)
    st_ = Counter(r["status"] for r in rs)
    p90 = durs[int(len(durs) * 0.9) - 1] if len(durs) >= 5 else (durs[-1] if durs else 0)
    print(f"{model[:38]:38} {len(rs):>5} {st_['completed']:>4} {st_['failed']:>4} {st_['interrupted']:>4} {st_['unfinished']:>5} "
          f"{(st.median(durs) if durs else 0):>6.1f} {p90:>6.1f} {st.median([r['calls'] for r in rs]):>9} "
          f"{st.median([len(r['tools']) for r in rs]):>9} {(100 * terr / tools if tools else 0):>8.1f}% "
          f"{sum(sum(r['stuck'].values()) for r in rs):>5} {sum(1 for r in rs if streak(r['tools']) >= 3):>8} "
          f"{(st.median([r['in_tok'] for r in rs]) / 1000):>8.1f}")
print()

print("== failure types (model -> exception type)")
fails = Counter((r["model"], r["fail"]) for r in R if r["status"] == "failed")
for (m, f), n in fails.most_common(15):
    print(f"  {n:>4}  {m[:38]:38} {f}")
print()
print("== model call errors (category)")
me = Counter()
for r in R:
    for k, v in r["model_err"].items():
        me[(r["model"], k)] += v
for (m, k), n in me.most_common(12):
    print(f"  {n:>4}  {m[:38]:38} {k}")
print()

print("== tools: calls / errors / runs where called 3+ times in a row")
calls, errs, streaky = Counter(), Counter(), Counter()
for r in R:
    calls.update(r["tools"])
    errs.update(r["tool_err"])
    prev, n, flagged = None, 0, set()
    for x in r["tools"] + [None]:
        if x == prev:
            n += 1
        else:
            if prev is not None and n >= 3:
                flagged.add(prev)
            prev, n = x, 1
    streaky.update(flagged)
print(f"  {'tool':34} {'calls':>6} {'err':>5} {'err%':>6} {'streak3+':>8}")
for name, n in calls.most_common(30):
    print(f"  {name[:34]:34} {n:>6} {errs[name]:>5} {100 * errs[name] / n:>5.1f}% {streaky[name]:>8}")
print()

print("== stuck detector fired:", dict(sum((r["stuck"] for r in R), Counter())))
print("== compactions:", sum(r["compact"] for r in R), " repairs:", sum(r["repair"] for r in R))
print()

print("== slowest 10 completed runs")
done = [r for r in R if isinstance(r["dur"], (int, float))]
for r in sorted(done, key=lambda r: -r["dur"])[:10]:
    print(f"  {r['date']} {r['id']} {r['model'][:26]:26} {r['status']:10} {r['dur']/1000:>6.0f}s calls={r['calls']:<3} tools={len(r['tools']):<3} | {compact_seq(r['tools'])}")
print()
print("== most tool errors 10 runs")
for r in sorted(R, key=lambda r: -sum(r["tool_err"].values()))[:10]:
    if not r["tool_err"]:
        break
    print(f"  {r['date']} {r['id']} {r['model'][:26]:26} {r['status']:10} err={sum(r['tool_err'].values()):<3} {dict(r['tool_err'].most_common(3))} | {compact_seq(r['tools'])}")
print()
print("== longest same-tool streaks 10 runs")
for r in sorted(R, key=lambda r: -streak(r["tools"]))[:10]:
    if streak(r["tools"]) < 3:
        break
    print(f"  {r['date']} {r['id']} {r['model'][:26]:26} {r['status']:10} streak={streak(r['tools'])} | {compact_seq(r['tools'])}")
