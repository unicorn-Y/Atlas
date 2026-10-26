"""U38 acceptance scenarios. No Electron process or screenshots are used."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scenario(name: str, action) -> None:
    print(f"U38 scenario: {name}", flush=True)
    action()


def cli_help(command: str, required: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "core") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-m", "atlas.cli", *command.split(), "--help"],
                            cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    check(result.returncode == 0, f"CLI help failed: {result.stderr[-1000:]}")
    for option in required:
        check(option in result.stdout, f"CLI option missing: {option}")


def main() -> None:
    from atlas.skills.agent_collections import AgentSkillCollections
    from atlas.skills.source_policy import get_policy, set_policy, skill_category, skill_load_allowed

    scenario("safe mode startup option", lambda: cli_help("chat", ["--safe-mode"]))
    scenario("CLI per-run skill preload options", lambda: cli_help("exec", ["--skills", "--skills-file"]))

    with tempfile.TemporaryDirectory(prefix="atlas-u38-") as temp:
        root = Path(temp)
        policy_file = root / "data" / "skill-source-policy.json"
        from atlas.skills import source_policy
        source_policy._path = lambda: policy_file
        defaults = get_policy()
        check(defaults["load"]["bundled"] and defaults["create"]["marketplace"], "default policy changed")
        set_policy({"load": {"marketplace": False}, "overrides": {"market-skill": True}})
        marketplace_skill = SimpleNamespace(name="market-skill", source="marketplace", path="/market/a/SKILL.md")
        check(skill_category(marketplace_skill) == "marketplace", "market source classification failed")
        check(skill_load_allowed(marketplace_skill), "explicit skill override failed")
        set_policy({"overrides": {"market-skill": False}})
        check(not skill_load_allowed(marketplace_skill), "explicit deny override failed")
        check(policy_file.exists(), "policy was not persisted")
        registry = SimpleNamespace(path=root / "registry.sqlite")
        collection = AgentSkillCollections(registry)
        collection.set_agent_skill("agent-a", "market-skill", enabled=True)
        collection.record_usage("market-skill", "agent-a")
        stats = collection.usage_stats("market-skill")
        check(stats["total_use_count"] == 1 and stats["agents"][0]["agent_id"] == "agent-a", "skill telemetry scenario failed")
        check(collection.remove_agent_skill("agent-a", "market-skill"), "agent skill removal failed")
        check(not collection.list_agent_skills("agent-a"), "agent skill relation remained")
        print("U38 scenario: persistent source policy and per-agent skill health PASS", flush=True)

    app = (ROOT / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    side = (ROOT / "frontend/src/renderer/components/SideChat.tsx").read_text(encoding="utf-8")
    shortcuts = (ROOT / "frontend/src/renderer/services/shortcuts.ts").read_text(encoding="utf-8")
    check("Ctrl+;" in shortcuts and "openSideChatWindow" in app, "side chat shortcut/window wiring missing")
    check("atlas:side-chat-selection" in app and "initialQuestion" in side, "selected-text side chat wiring missing")
    check("ephemeral: true" in side and "window.confirm" in side and "不进入历史、搜索或同步" in side,
          "temporary chat lifecycle disclosure/cleanup missing")
    print("U38 scenario: side chat and temporary chat source checks PASS", flush=True)

    export = (ROOT / "frontend/src/renderer/store/useAtlasStore.ts").read_text(encoding="utf-8")
    sidebar = (ROOT / "frontend/src/renderer/shell/Sidebar.tsx").read_text(encoding="utf-8")
    for marker in ("atlas.transcript.v1", "jsonl", "text/html", "text/markdown", "openMessageEditor"):
        check(marker in export, f"export format marker missing: {marker}")
    check("JSONL" in sidebar and "HTML" in sidebar and "用编辑器打开" in sidebar,
          "export actions missing from conversation menu")
    print("U38 scenario: versioned transcript export formats and open action PASS", flush=True)
    print("U38 CHECK PASS")


if __name__ == "__main__":
    main()
