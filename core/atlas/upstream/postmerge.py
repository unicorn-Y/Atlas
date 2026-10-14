"""更新器合并追新提交之后、在正在用的仓库里做的收尾（由 scripts/atlas-update.mjs 调用）。

- 本机配置 ``config/atlas.toml`` 不进 git：把里面 MCP 启动参数的包版本对齐到
  ``config/atlas.example.toml``（追新只改得到示例配置），两台电脑各自对齐。
- 合并完成后删掉 ``pending-merge.json``。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from atlas.upstream import sources
from atlas.upstream.staging import PENDING

_SPEC = re.compile(r"(@?[\w.-]+(?:/[\w.-]+)?)@(\d[\w.+-]*)")


def sync_mcp_versions(example: Path, live: Path) -> list[str]:
    """把 live 里 ``包@版本`` 的版本换成 example 里同一个包的版本。返回改了的包。"""
    if not example.exists() or not live.exists():
        return []
    wanted = {name: version for name, version in _SPEC.findall(example.read_text(encoding="utf-8"))}
    text = live.read_text(encoding="utf-8")
    changed: list[str] = []

    def swap(match: re.Match[str]) -> str:
        name, version = match.group(1), match.group(2)
        target = wanted.get(name)
        if target and target != version:
            changed.append(f"{name} {version} → {target}")
            return f"{name}@{target}"
        return match.group(0)

    new = _SPEC.sub(swap, text)
    if changed:
        backup = live.with_suffix(live.suffix + ".bak-upstream")
        shutil.copy2(live, backup)
        live.write_text(new, encoding="utf-8")
    return changed


def main() -> int:
    from atlas.config import CONFIG_PATH, PROJECT_ROOT
    from atlas.upstream.check import upstream_root

    repo = PROJECT_ROOT
    changed = sync_mcp_versions(repo / "config" / "atlas.example.toml", CONFIG_PATH)
    for line in changed:
        print(f"[upstream] MCP {line}")
    pending = upstream_root() / PENDING
    if pending.exists():
        data = json.loads(pending.read_text(encoding="utf-8"))
        merged = sources.run([*sources.GIT, "merge-base", "--is-ancestor", data["commit"], "HEAD"],
                             cwd=repo, timeout=60)
        if merged.returncode == 0:
            pending.unlink()
    return 0
