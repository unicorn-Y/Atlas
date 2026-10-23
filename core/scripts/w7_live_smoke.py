"""W7 smoke coverage for bounded local file reads and workspace search."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path


def _query_pagination(root: Path) -> None:
    from atlas.tools.workspace_queries import grep_workspace, glob_workspace

    source = root / "matches.py"
    source.write_text("\n".join(["needle " + ("x" * 600) + str(i) for i in range(4)]), encoding="utf-8")
    page = grep_workspace(str(root), pattern="needle", path=".", literal=True, limit=2)
    if len(page["matches"]) != 2 or not page["truncated"] or page["next_offset"] != 2:
        raise RuntimeError("grep did not return a bounded first page")
    if not page["matches"][0].get("line_truncated") or len(page["matches"][0]["text"]) > 520:
        raise RuntimeError("grep did not bound an oversized result line")
    next_page = grep_workspace(str(root), pattern="needle", path=".", literal=True, limit=2, offset=2)
    if [item["line"] for item in next_page["matches"]] != [3, 4]:
        raise RuntimeError("grep offset did not resume after the previous page")
    all_matches = grep_workspace(str(root), pattern="needle", path=".", literal=True, limit=0)
    if len(all_matches["matches"]) != 4 or all_matches["truncated"]:
        raise RuntimeError("grep limit=0 did not return all matches under the safe cap")
    files = glob_workspace(str(root), pattern="*.py")
    if files["matches"] != ["matches.py"]:
        raise RuntimeError("glob results were not returned for the requested pattern")
    for index in range(105):
        (root / f"item-{index:03}.py").touch()
    default_glob = glob_workspace(str(root), pattern="item-*.py")
    if (len(default_glob["matches"]) != 100 or not default_glob["truncated"]
            or "narrow" not in default_glob.get("hint", "")):
        raise RuntimeError("glob default limit or truncation hint was missing")
    short_glob = glob_workspace(str(root), pattern="item-*.py", limit=2)
    if len(short_glob["matches"]) != 2 or not short_glob["truncated"]:
        raise RuntimeError("glob caller-configured limit was not applied")
    print("glob_limits: default 100, custom cap, and truncation hint passed")
    print("grep pagination: stable offsets, line clipping, and unbounded sentinel passed")


async def _default_read_page(root: Path) -> None:
    from atlas.tools.local_execution import LocalExecutionRuntime

    runtime = LocalExecutionRuntime()
    runtime.permission_mode = "full_access"
    source = root / "large.txt"
    source.write_text("".join(f"line-{i}\n" for i in range(1, 2003)), encoding="utf-8")
    try:
        result = await runtime.call_tool("local_file", {
            "action": "read", "path": str(source), "_atlas_workspace": str(root),
        }, run_id="w7-read-limit")
    finally:
        await runtime.shutdown()
    body = result.get("data") if isinstance(result.get("data"), dict) else result
    if result.get("is_error") or body.get("next_offset") != 2001 or body.get("complete"):
        raise RuntimeError("default read did not cap at 2,000 lines with continuation metadata")
    if len(body.get("content", "").splitlines()) != 2000:
        raise RuntimeError("default read page did not contain exactly 2,000 lines")
    print("read paging: default first page capped at 2,000 lines with continuation")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-w7-smoke-") as name:
        root = Path(name)
        _query_pagination(root)
        await _default_read_page(root)
    print("W7 LIVE SMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
