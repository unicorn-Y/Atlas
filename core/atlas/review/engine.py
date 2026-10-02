# Ported from NousResearch/hermes-agent@e287231:agent/review_engine.py (MIT, (c) Nous Research).
# Ported the reviewer goal/briefing structure (evidence-first, no padding findings) and the
# delegate-a-child dispatch shape; Atlas replaces the conversation-excerpt evidence with a
# git diff collected read-only, adds a strict findings JSON schema, the review_command /
# submit_findings tools and the review.findings queue event (ATLAS-C6 contract section 5).

"""P2 /review — child-runtime code review engine.

Surfaces call :func:`parse_scope` + :func:`collect_diff` + :func:`build_dispatch_prompt`
and hand the prompt to the parent agent; the parent dispatches one read-only reviewer
child through ``delegate_task`` and forwards the child's findings JSON to
``submit_findings``, which emits the ``review.findings`` queue event (contract 2.2).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

# Diff text is capped so a huge branch cannot blow the child's context; the note tells the
# reviewer how to reach the rest with its own read-only git access.
MAX_DIFF_LINES = 2000

# review_command output cap (~8000 chars) and its single-command timeout.
COMMAND_OUTPUT_CHARS = 8000
COMMAND_TIMEOUT_SECONDS = 120

SEVERITIES = ("blocker", "major", "minor")

SCOPE_LABELS = {
    "working_tree": "当前未提交改动",
}

SEVERITY_RULES = {
    "blocker": "会造成数据丢失、崩溃、安全漏洞或明显错误行为，必须修复的问题。",
    "major": "功能或可维护性上的确定缺陷，应当修复的问题。",
    "minor": "小问题、边界风险或值得注意的提示，可择机处理。",
}

FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "相对工作目录的文件路径"},
            "line": {"type": ["integer", "null"], "description": "1 起始行号，定位不了为 null"},
            "range": {"type": ["array", "null"], "items": {"type": "integer"},
                      "minItems": 2, "maxItems": 2, "description": "[起始行, 结束行] 或 null"},
            "severity": {"type": "string", "enum": list(SEVERITIES)},
            "title": {"type": "string", "description": "一句话标题"},
            "explanation": {"type": "string", "description": "为什么是问题、会造成什么后果"},
            "evidence": {"type": "string", "description": "file:line 的代码原文或 diff 片段"},
            "suggested_fix": {"type": "string", "description": "建议的修法"},
        },
        "required": ["file", "severity", "title", "explanation"],
        "additionalProperties": False,
    },
}


def is_review_request(content: str) -> bool:
    """True when a run message invokes /review (variants included, English canonical)."""
    if not isinstance(content, str):
        return False
    normalized = " ".join(content.split())
    lowered = normalized.lower()
    for prefix in ("/review", "/审查"):
        if lowered.startswith(prefix):
            rest = normalized[len(prefix):]
            if rest == "" or rest[0].isspace():
                return True
    return False


def parse_scope(content: str) -> dict[str, Any]:
    """{"scope": working_tree|branch|commit, "ref": str|None, "user_prompt": str}."""
    tokens = " ".join(str(content or "").split()).split(" ")
    body = tokens[1:]
    scope: str = "working_tree"
    ref: str | None = None
    if len(body) >= 2 and body[0].lower() in {"branch", "分支"}:
        scope, ref, body = "branch", body[1], body[2:]
    elif len(body) >= 2 and body[0].lower() in {"commit", "提交"}:
        scope, ref, body = "commit", body[1], body[2:]
    return {"scope": scope, "ref": ref, "user_prompt": " ".join(body).strip()}


def scope_label(scope_result: dict[str, Any]) -> str:
    """Chinese display label for a scope, per contract 5."""
    kind = str(scope_result.get("scope") or "working_tree")
    if kind == "branch":
        return f"分支 {scope_result.get('ref')} 相对 main"
    if kind == "commit":
        return f"提交 {scope_result.get('ref')}"
    return SCOPE_LABELS["working_tree"]


def _run_git(workspace: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, shell=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError as exc:
        raise ValueError("没有找到 git 命令，无法收集审查差异。请确认本机已安装 Git。") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("git 命令执行超时，无法收集审查差异。") from exc


def _git_ok(workspace: str, *args: str) -> str:
    proc = _run_git(workspace, *args)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ValueError(f"git 命令失败（{' '.join(args[:2])}）：{detail[-1] if detail else '未知错误'}")
    return proc.stdout


def _truncate_lines(text: str, limit: int = MAX_DIFF_LINES) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text, False
    note = (
        f"\n…… diff 共 {len(lines)} 行，超过 {limit} 行上限，已截断。"
        "需要看剩余部分时，用 review_command 自己跑 git diff / git show。"
    )
    return "\n".join(lines[:limit]) + note, True


def collect_diff(workspace: str, scope: dict[str, Any]) -> dict[str, Any]:
    """Read-only git collection of the review evidence for one scope (contract 5)."""
    ws = str(workspace or "").strip()
    if not ws or not os.path.isdir(ws):
        raise ValueError(f"工作目录不存在，无法审查：{ws or '(空)'}")
    probe = _run_git(ws, "rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        raise ValueError("这个目录不是 Git 仓库，无法执行 /review。请先把对话的工作目录切到一个 Git 仓库。")
    kind = str(scope.get("scope") or "working_tree")
    result: dict[str, Any] = {
        "scope": kind, "ref": scope.get("ref"),
        "diff_text": "", "stat": "", "truncated": False,
        "scope_label": scope_label({**scope, "scope": kind}),
    }
    if kind == "working_tree":
        status = _git_ok(ws, "status", "--porcelain")
        diff = _run_git(ws, "diff", "HEAD").stdout
        result["stat"] = _run_git(ws, "diff", "HEAD", "--stat").stdout.strip()
        result["untracked"] = [
            line[3:].strip().strip('"') for line in status.splitlines() if line.startswith("?? ")
        ]
        result["status"] = status.rstrip()
    elif kind == "branch":
        ref = str(scope.get("ref") or "").strip()
        if not ref:
            raise ValueError("分支审查需要一个分支名，例如 /review branch feature-x。")
        _git_ok(ws, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        # Three-dot diff against the merge base, reviewed branch on the right: with HEAD on
        # main this is exactly "分支 <name> 相对 main"（the contract's literal <name>...HEAD
        # ordering yields an empty diff in that, the common, case）.
        range_spec = f"HEAD...{ref}"
        diff = _run_git(ws, "diff", range_spec).stdout
        result["stat"] = _run_git(ws, "diff", "--stat", range_spec).stdout.strip()
    elif kind == "commit":
        ref = str(scope.get("ref") or "").strip()
        if not ref:
            raise ValueError("提交审查需要一个 commit SHA，例如 /review commit 6df1add。")
        _git_ok(ws, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        diff = _run_git(ws, "show", ref).stdout
        result["stat"] = _git_ok(ws, "show", "--stat", "--format=", ref).strip()
    else:
        raise ValueError(f"未知的审查范围：{kind}")
    result["diff_text"], result["truncated"] = _truncate_lines(diff)
    return result


def build_child_goal(scope_result: dict[str, Any], user_prompt: str = "") -> str:
    """Full reviewer briefing handed to delegate_task as the child's goal.

    Structure ported from Hermes ``build_review_task``/``_REVIEW_GOAL``: the reviewer is an
    independent investigator that must verify from evidence, run what is feasible, and
    report structured findings; adapted to Atlas' read-only reviewer with a strict JSON
    findings contract and an explicit no-padding rule.
    """
    label = scope_result.get("scope_label") or scope_label(scope_result)
    focus = " ".join(str(user_prompt or "").split())
    lines = [
        f"独立代码审查：{label}。" + (f"用户特别关注：{focus}" if focus else ""),
        "",
        "你是 /review 派出的独立高级审查员，一位只读的调查员。下面给出的差异文本是你的起点证据；"
        "不要只看 diff 下结论，先打开涉及的文件读上下文，能验证的就去验证（跑测试、lint、类型检查），"
        "然后给出完整的结构化审查：改了什么、是否正确完整、有哪些确定的缺陷或风险（附 file:line 和代码证据）、"
        "哪些是验证过的、哪些只是读到的。",
        "",
        "--- 审查差异（{label}） ---".format(label=label),
    ]
    if scope_result.get("untracked"):
        lines.append("以下未跟踪文件不在 diff 里，需要的话直接读取原文：")
        lines.extend(f"- {name}" for name in scope_result["untracked"][:50])
        lines.append("")
    if scope_result.get("stat"):
        lines += ["--- 变更统计 ---", str(scope_result["stat"]), ""]
    lines += [str(scope_result.get("diff_text") or "（这个范围内没有差异。）"), ""]
    lines += [
        "--- 差异结束 ---",
        "",
        "审查纪律（必须遵守）：",
        "1. 只读。不得修改、创建、移动或删除任何文件，不得改仓库状态，不得联网安装依赖。"
        "读文件和搜索用 local_file 工具（action 取 read/search/glob/list/stat；"
        "read_file/search_files 在只读会话里会被拒），另外可用 review_command 运行只读验证命令"
        "（测试/lint/类型检查/git 查看命令）；会写文件的命令会被工具直接拒绝。",
        "2. 证据优先。每条发现都必须给出 file（相对路径）、line（1 起始行号）和 evidence"
        "（从 diff 或文件里摘出的代码原文）。拿不准的先去读文件或跑只读命令验证，不要凭感觉写。",
        "3. 不凑数量。没有问题就返回空数组 []，这同样是有效结论。"
        "不要报告纯风格偏好、大规模重构建议或无法落地的臆测性风险。",
        "4. 严重级别定义：" + "；".join(f"{name}={text}" for name, text in SEVERITY_RULES.items()),
        "5. 直接、具体，不要软化措辞；结论会原样带给用户。",
        "",
        "最终消息格式（严格遵守）：只输出一个 JSON 数组，不要 markdown 代码围栏，不要数组之外的任何解释文字。"
        "每个元素形如：" + json.dumps({
            "file": "src/app.py", "line": 12, "range": [12, 20], "severity": "major",
            "title": "一句话标题", "explanation": "为什么是问题、会造成什么",
            "evidence": "file:line 的代码原文", "suggested_fix": "建议修法",
        }, ensure_ascii=False),
        "没有发现问题时输出 []。",
    ]
    if focus:
        lines += ["", f"用户补充的审查重点：{focus}"]
    return "\n".join(lines)


def build_dispatch_prompt(scope_result: dict[str, Any], user_prompt: str = "") -> str:
    """Parent-side prompt: dispatch one reviewer child, forward its findings, summarize."""
    label = scope_result.get("scope_label") or scope_label(scope_result)
    scope = str(scope_result.get("scope") or "working_tree")
    goal = build_child_goal(scope_result, user_prompt)
    return "\n".join([
        f"用户请求审查：{label}。请严格按以下步骤执行，不要自己动手审查：",
        "",
        "1. 调用一次 delegate_task（background=false，agent 传 \"general\"，"
        "permission_mode 传 \"read_only\" 让审查员子任务强制只读），把下面「审查员简报」的全部原文"
        "作为 goal 参数传入，不要改写、不要删减。",
        "2. 子任务返回后，从返回文本里提取 findings JSON 数组（提取第一个以 [ 开头、以 ] 结尾的块），"
        f"原样调用 submit_findings 提交：findings_json 传数组原文，不要重新格式化、不要增删字段；"
        f'同时传 scope="{scope}"、scope_label="{label}"。子任务没有返回数组时，findings_json 传 "[]"。',
        "3. 最后输出一段简短中文总结：按 blocker/major/minor 分别报数；一条都没有时写「没有发现问题」。",
        "",
        "findings 条目字段：file、line（1 起始或 null）、range（[起,止] 或 null）、"
        "severity（blocker|major|minor）、title、explanation、evidence、suggested_fix。",
        "",
        "--- 审查员简报（原样作为 delegate_task 的 goal） ---",
        goal,
        "--- 简报结束 ---",
    ])


# ---------------------------------------------------------------------------
# Findings parsing (tolerant) ------------------------------------------------


def parse_findings(text: str) -> list[dict[str, Any]]:
    """Extract the first JSON array and normalize every entry to the 2.2 schema.

    Invalid entries are dropped; no findings at all returns []. Tolerates a markdown
    fence, surrounding prose and trailing commas.
    """
    block = _extract_json_array(str(text or ""))
    if block is None:
        return []
    try:
        parsed = json.loads(block)
    except (ValueError, TypeError):
        try:
            parsed = json.loads(re.sub(r",\s*([\]}])", r"\1", block))
        except (ValueError, TypeError):
            return []
    if not isinstance(parsed, list):
        return []
    findings = []
    for item in parsed:
        normalized = _normalize_finding(item)
        if normalized is not None:
            findings.append(normalized)
    return findings


def _extract_json_array(text: str) -> str | None:
    """First top-level ``[ ... ]`` block in ``text``, honoring strings and escapes."""
    stripped = text.strip()
    if stripped.startswith("["):
        candidate = _match_bracket(stripped, 0)
        if candidate is not None:
            return candidate
    start = -1
    for index, char in enumerate(text):
        if char == "[" and not _in_string(text, index):
            start = index
            break
    if start < 0:
        return None
    return _match_bracket(text, start)


def _in_string(text: str, index: int) -> bool:
    in_string = False
    escaped = False
    for char in text[:index]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
    return in_string


def _match_bracket(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _normalize_finding(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    file = str(item.get("file") or "").strip()
    title = str(item.get("title") or "").strip()
    explanation = str(item.get("explanation") or "").strip()
    if not file or not title or not explanation:
        return None
    severity = str(item.get("severity") or "").strip().lower()
    if severity not in SEVERITIES:
        severity = "minor"
    return {
        "file": file,
        "line": _coerce_line(item.get("line")),
        "range": _coerce_range(item.get("range")),
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "evidence": str(item.get("evidence") or ""),
        "suggested_fix": str(item.get("suggested_fix") or ""),
    }


def _coerce_line(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _coerce_range(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    start, end = _coerce_line(value[0]), _coerce_line(value[1])
    if start is None or end is None:
        return None
    return [start, end]


# ---------------------------------------------------------------------------
# review_command: strict read-only verification ------------------------------
#
# Refusal rule set ported from the Hermes danger detectors (agent side tables in
# tools/ plus their Atlas port in atlas/safety/hermes_detection.py): deletion,
# writes via shell operators, mutating git subcommands, permission/process/system
# changes, package installs and remote-code execution. review_command is stricter
# than the safety reviewer because it must NEVER write, so the git side is a
# read-verb allowlist and plain redirects are refused outright.

# Binaries that are never read-only, matched on the segment's command word.
_DENY_BINARIES = {
    # deletion
    "rm", "rmdir", "rd", "del", "erase", "unlink", "shred", "srm", "remove-item", "ri",
    # file writes / moves
    "mv", "move", "cp", "copy", "copy-item", "move-item", "install", "tee", "tee-object",
    "touch", "mkfile", "mkdir", "md", "patch", "ln", "mklink",
    # permissions
    "chmod", "chown", "chgrp", "chattr", "icacls", "attrib", "takeown", "cacls", "setfacl",
    # processes / services
    "kill", "killall", "pkill", "taskkill", "stop-process", "stop-service", "sc",
    # privilege / system
    "sudo", "su", "doas", "runas", "shutdown", "reboot", "halt", "poweroff",
    "stop-computer", "restart-computer", "bcdedit", "reg", "regedit", "regadd",
    "diskpart", "mkfs", "dd", "vssadmin", "wbadmin", "cipher", "format", "format-volume",
    "clear-disk", "set-executionpolicy",
}

_DENY_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfind\b[^|;&\n]*\s-delete\b", re.I), "find -delete 会删除文件"),
    (re.compile(r"\bxargs\b[^|;&\n]*\b(?:rm|del)\b", re.I), "xargs 批量删除"),
    (re.compile(r"\bsed\b[^|;&\n]*\s(?:-[^\"\s]*i\b|--in-place\b)", re.I), "sed -i 会原地改文件"),
    (re.compile(r"\b(?:npm|pnpm|pnpx|npx|yarn)\s+(?:i\b|install\b|add\b|remove\b|uninstall\b|rm\b|update\b|upgrade\b|link\b)", re.I),
     "安装、更新或卸载依赖包"),
    (re.compile(r"\bpip(?:3)?\s+(?:install|uninstall)\b|\bpython(?:3)?\s+-m\s+pip\s+(?:install|uninstall)\b", re.I),
     "安装或卸载 Python 包"),
    (re.compile(r"\buv\s+(?:pip\s+)?(?:install|uninstall|sync|add|remove|lock)\b", re.I), "安装或同步依赖"),
    (re.compile(r"\bcargo\s+(?:install|add|remove|uninstall)\b|\bpoetry\s+(?:install|add|remove|update)\b", re.I),
     "安装依赖"),
    (re.compile(r"\b(?:apt|apt-get|dnf|yum|brew|choco|winget|scoop)\s+(?:install|remove|uninstall|upgrade|update)\b", re.I),
     "安装或卸载系统软件包"),
    (re.compile(r"\b(?:curl|wget|iwr|invoke-webrequest|invoke-restmethod|irm)\b[^|;&\n]*\s(?:-o\b|-O\b|--output|--output-document|-outfile|-outfile\s)", re.I),
     "下载文件到磁盘"),
    (re.compile(r"\b(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^|;&\n]*\|\s*(?:\w*sh\b|bash\b|zsh\b|powershell\b|pwsh\b|cmd\b|iex\b|invoke-expression\b|python\b)", re.I),
     "下载并执行远程脚本"),
)

# git subcommands that only read the repository.
_GIT_READ_VERBS = {
    "status", "log", "show", "diff", "blame", "grep", "ls-files", "ls-remote",
    "rev-parse", "cat-file", "shortlog", "describe", "merge-base", "diff-tree",
    "rev-list", "name-rev", "whatchanged", "reflog", "count-objects",
    "verify-commit", "verify-tag", "for-each-ref", "check-ignore", "check-attr",
    "help", "version", "var", "difftool",
}

_GIT_BRANCH_FLAGS = {
    "-a", "-l", "-v", "-vv", "--list", "--show-current", "--contains", "--no-contains",
    "--points-at", "--merged", "--no-merged", "--sort", "--format", "--column", "-r",
}

# Code payloads after -c/-e/-p must not write, spawn or import-exec anything.
_PAYLOAD_WRITE = re.compile(
    r"open\s*\(|shutil\.|os\.(?:remove|unlink|rmdir|removedirs|rename|replace|makedirs|mkdir)"
    r"|pathlib[^\n]*\.(?:write_text|write_bytes|unlink|rmdir)\b|\.write(?:_text|_bytes)?\s*\("
    r"|\bsubprocess\b|\bos\.system\b|\bos\.exec|\beval\s*\(|\bexec\s*\(|__import__",
    re.I)

_INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "deno", "bun"}
_PAYLOAD_FLAGS = {"-c", "-e", "-p", "--eval", "--print"}


def check_command_read_only(command: str) -> str | None:
    """Refusal reason for a review_command candidate, or None when it may run."""
    text = str(command or "").strip()
    if not text:
        return "review_command 需要一条要运行的命令。"
    # fd duplication (2>&1) is not a file write; drop it before the redirect scan.
    cleaned = re.sub(r"\d*>>&?\d+", " ", text)
    if ">" in cleaned:
        return "审查命令不允许重定向写文件（> 或 >>）。请只运行把结果打印到 stdout 的只读命令。"
    if re.search(r"`|\$\(|<\(", cleaned):
        return "审查命令不允许命令替换（$(...)、反引号或进程替换），请直接写出要运行的完整命令。"
    for segment in re.split(r"\||;|&|\n", cleaned):
        tokens = _split_tokens(segment)
        if not tokens:
            continue
        head = re.sub(r"\.exe$", "", Path(tokens[0]).name.lower())
        if head in _DENY_BINARIES:
            return f"审查命令只允许只读操作，拒绝执行 {tokens[0]}（会改动文件、系统或仓库状态）。"
        if head == "git":
            reason = _check_git_read_only(tokens[1:])
            if reason:
                return reason
            continue
        if head in _INTERPRETERS:
            reason = _check_payload_read_only(tokens[1:])
            if reason:
                return reason
        for pattern, label in _DENY_RULES:
            if pattern.search(segment):
                return f"审查命令只允许只读操作：{label}。"
    # Backstop: the ported Hermes detector (recursive deletes, remote pipes, floors...).
    from atlas.safety.detection import detect_danger

    findings = detect_danger(text)
    if findings:
        return "审查命令只允许只读操作：" + "；".join(findings[:2]) + "。"
    return None


def _split_tokens(segment: str) -> list[str]:
    try:
        if os.name == "nt":
            tokens = shlex.split(segment, posix=False)
            unquoted = []
            for token in tokens:
                if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
                    token = token[1:-1]
                if token:
                    unquoted.append(token)
            return unquoted
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _check_git_read_only(rest: list[str]) -> str | None:
    verb = ""
    for index, token in enumerate(rest):
        if token.startswith("-"):
            # -C <path> consumes a value; other short flags do not.
            if token == "-C":
                index += 1
            continue
        verb = re.sub(r"\.exe$", "", Path(token).name.lower())
        rest = rest[index + 1:]
        break
    if not verb:
        return "git 命令缺少子命令。"
    if verb in _GIT_READ_VERBS:
        return None
    if verb in {"branch", "tag"}:
        flags = [token for token in rest if token.startswith("-")]
        operands = [token for token in rest if not token.startswith("-")]
        if operands or any(flag not in _GIT_BRANCH_FLAGS for flag in flags):
            return f"git {verb} 只允许查看列表（git {verb} 不带参数或 --list）。"
        return None
    if verb == "config":
        if any(token == "--list" or token.startswith("--get") for token in rest):
            return None
        return "git config 只允许 --get / --list 读取配置。"
    if verb == "worktree":
        if rest and rest[0] == "list":
            return None
        return "git worktree 只允许 list。"
    if verb == "stash":
        if not rest or rest[0] in {"list", "show"}:
            return None
        return "git stash 只允许 list / show。"
    if verb == "remote":
        if not rest or rest[0] in {"-v", "get-url"}:
            return None
        return "git remote 只允许查看远端列表。"
    return f"「git {verb}」不是只读的 git 命令，审查时禁止执行。请只使用查看类 git 命令（status/log/show/diff/blame 等）。"


def _check_payload_read_only(args: list[str]) -> str | None:
    for index, token in enumerate(args):
        base = token.lower().strip()
        if base in _PAYLOAD_FLAGS and index + 1 < len(args):
            payload = args[index + 1]
            if _PAYLOAD_WRITE.search(payload):
                return "审查命令只允许只读操作：-c/-e 内联代码里包含写文件、执行子进程或动态导入的操作。"
    return None


def run_review_command(
    command: str, cwd: str | None = None, timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], str]:
    """Run one read-only verification command; returns (data, text) and never writes.

    Raises ValueError with a Chinese refusal/说明 message when refused, when the
    directory does not exist or when the command times out.
    """
    refusal = check_command_read_only(command)
    if refusal:
        raise ValueError(refusal)
    directory = Path(str(cwd or ".")).expanduser()
    if not directory.is_dir():
        raise ValueError(f"cwd 目录不存在：{directory}")
    tokens = _split_tokens(str(command))
    if not tokens:
        raise ValueError("review_command 需要一条要运行的命令。")
    try:
        proc = subprocess.run(
            tokens, cwd=str(directory), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, shell=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"审查命令超时（上限 {timeout} 秒），已终止。请换成更快或更小范围的验证命令。") from exc
    except FileNotFoundError as exc:
        raise ValueError(f"找不到要运行的程序：{tokens[0]}") from exc
    output = (proc.stdout or "").rstrip()
    stderr = (proc.stderr or "").rstrip()
    if stderr:
        output = f"{output}\n--- stderr ---\n{stderr}" if output else stderr
    body = output.strip() or "（命令没有输出。）"
    truncated = False
    if len(body) > COMMAND_OUTPUT_CHARS:
        body = body[:COMMAND_OUTPUT_CHARS] + "\n……输出过长，已截断……"
        truncated = True
    text = f"$ {command}\n(exit code {proc.returncode})\n{body}"
    data = {
        "command": str(command), "cwd": str(directory),
        "returncode": proc.returncode, "truncated": truncated,
    }
    return data, text


# ---------------------------------------------------------------------------
# submit_findings: emit the review.findings queue event -----------------------


async def emit_findings_event(
    event_queue: Any, *, scope: str, scope_label: str, workspace: str, findings: list[dict[str, Any]],
) -> None:
    if event_queue is None:
        return
    await event_queue.put({
        "type": "review.findings",
        "data": {
            "scope": str(scope or "working_tree"),
            "scope_label": str(scope_label or SCOPE_LABELS.get(str(scope), "当前未提交改动")),
            "workspace": str(workspace or ""),
            "findings": findings,
        },
    })


async def handle_agent_tool(name: str, arguments: dict[str, Any], ctx: Any) -> tuple[dict[str, Any], str]:
    """Dispatch entry for the two review tools inside the Atlas tool-execution node.

    ``ctx`` is the AgentRunContext (needs ``event_queue`` and ``workspace``).
    Returns (data, result_text); refusals raise ValueError so the call surfaces as a
    tool error, matching the neighboring Atlas-native branches.
    """
    arguments = dict(arguments or {})
    workspace = str(getattr(ctx, "workspace", "") or "")
    if name == "review_command":
        cwd = str(arguments.get("cwd") or "").strip() or workspace
        return await asyncio.to_thread(
            run_review_command, str(arguments.get("command") or ""), cwd,
        )
    if name == "submit_findings":
        findings = parse_findings(str(arguments.get("findings_json") or ""))
        scope = str(arguments.get("scope") or "working_tree")
        label = str(arguments.get("scope_label") or "") or scope_label({"scope": scope, "ref": None})
        await emit_findings_event(
            getattr(ctx, "event_queue", None),
            scope=scope, scope_label=label, workspace=workspace, findings=findings,
        )
        data = {"scope": scope, "scope_label": label, "count": len(findings), "findings": findings}
        text = (
            f"已记录 {len(findings)} 条发现。" if findings
            else "已记录 0 条发现：本次审查没有发现问题。"
        )
        return data, text
    raise ValueError(f"未知的审查工具：{name}")


# ---------------------------------------------------------------------------
# tools.registry registration (idempotent; live runs rebind via bind_atlas_tools)


_REVIEW_TOOL_SCHEMAS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("review_command", {
        "name": "review_command",
        "description": (
            "Run a read-only verification command during a code review (tests, lint, "
            "typecheck, git read commands). Write-capable or mutating commands are refused."
        ),
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "The command line to run."},
            "cwd": {"type": "string", "description": "Working directory; defaults to the current workspace."},
        }, "required": ["command"], "additionalProperties": False},
    }),
    ("submit_findings", {
        "name": "submit_findings",
        "description": (
            "Submit code-review findings and emit the review.findings event. Pass the "
            "reviewer's JSON findings array verbatim; an empty array is valid."
        ),
        "parameters": {"type": "object", "properties": {
            "findings_json": {"type": "string", "description": "JSON array of findings, verbatim from the reviewer."},
            "scope": {"type": "string", "description": "Review scope: working_tree, branch, or commit."},
            "scope_label": {"type": "string", "description": "Chinese display label of the review scope."},
        }, "required": ["findings_json"], "additionalProperties": False},
    }),
)


def _resolve_active_context(session_id: str) -> tuple[Any, Any, Any]:
    """(agent, runtime, loop) for a live run, mirroring tool_registry's lookup."""
    from atlas.engine import tool_registry as atlas_tool_registry

    active = getattr(atlas_tool_registry, "_active_contexts", {}).get(str(session_id or ""))
    if active is not None:
        return active
    thread_context = getattr(atlas_tool_registry, "_context", None)
    return (
        getattr(thread_context, "agent", None),
        getattr(thread_context, "runtime", None),
        getattr(thread_context, "loop", None),
    )


def _make_registry_handler(name: str):
    def handler(args: dict[str, Any], **kwargs: Any) -> str:
        _agent, runtime, loop = _resolve_active_context(str(kwargs.get("session_id") or ""))
        if runtime is None or loop is None:
            return json.dumps({"error": "Atlas 审查工具只能在运行中的会话里调用。"}, ensure_ascii=False)

        async def call() -> tuple[dict[str, Any], str]:
            return await handle_agent_tool(name, args, runtime)

        try:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not None and running is loop:
                raise RuntimeError("审查工具不能在事件循环线程里同步调用。")
            _data, text = asyncio.run_coroutine_threadsafe(call(), loop).result(
                timeout=COMMAND_TIMEOUT_SECONDS + 30,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": f"审查工具执行失败：{exc}"}, ensure_ascii=False)
        return text

    return handler


def register_review_tools() -> None:
    """Register review_command + submit_findings in the Hermes tool registry (idempotent).

    Mirrors how bind_atlas_tools registers new_context_window; a later live run
    rebinds dispatch through bind_atlas_tools with override=True, so re-running
    this must never clobber that binding (hence the get_entry guard).
    """
    # 审查工具必须常驻（ambient）：tool_search 的可延迟规则会把不在 hermes
    # toolsets._HERMES_CORE_TOOLS 里的工具换成桥接桩，审查员直接调用会被
    # "Tool '...' does not exist" 拒绝——与 clarify 刻意不延迟是同一个理由。
    import toolsets as hermes_toolsets

    for _ambient in ("submit_findings", "review_command"):
        if _ambient not in hermes_toolsets._HERMES_CORE_TOOLS:
            hermes_toolsets._HERMES_CORE_TOOLS.append(_ambient)

    from tools.registry import registry

    for name, schema in _REVIEW_TOOL_SCHEMAS:
        if registry.get_entry(name) is not None:
            continue
        registry.register(
            name=name, toolset="atlas", schema=schema,
            handler=_make_registry_handler(name), is_async=False,
            description=str(schema["description"]), override=True,
        )


# ---------------------------------------------------------------------------
# HTTP surface ----------------------------------------------------------------


def register_review_routes(app: Any) -> None:
    """Minimal HTTP surface for this wave: the findings JSON schema."""

    @app.get("/api/review/schema")
    def review_schema() -> dict[str, Any]:
        return {
            "event": "review.findings",
            "severities": list(SEVERITIES),
            "scopes": ["working_tree", "branch", "commit"],
            "finding": FINDINGS_SCHEMA["items"],
        }
