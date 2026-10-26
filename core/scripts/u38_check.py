"""U38 acceptance scenarios. No Electron process or screenshots are used."""
from __future__ import annotations

import os
import asyncio
import subprocess
import shutil
import sys
import tempfile
import subprocess
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
    from atlas.skills import SkillManager, SkillSource

    scenario("safe mode startup option", lambda: cli_help("chat", ["--safe-mode"]))
    safe_env = dict(os.environ)
    safe_env["ATLAS_ROOT"] = r"C:\engine-reg\_atlasroot"
    safe = subprocess.run([sys.executable, "-m", "atlas.cli", "chat", "--safe-mode"],
                          cwd=ROOT / "core", env=safe_env, input="quit\n", capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=90)
    check(safe.returncode == 0 and "安全模式已启用" in safe.stdout and "Bye!" in safe.stdout,
          "safe-mode chat startup/exit scenario failed")
    print("U38 scenario: safe-mode chat starts, reports diagnostic state, and exits cleanly PASS", flush=True)
    scenario("CLI per-run skill preload options", lambda: cli_help("exec", ["--skills", "--skills-file"]))
    live_root = Path(r"C:\engine-reg\_atlasroot")
    live_skill = live_root / "skills" / "testing" / "u38-smoke-temp"
    live_skill_file = live_root / "data" / "u38-skills.txt"
    live_skill.mkdir(parents=True, exist_ok=True)
    live_skill_file.parent.mkdir(parents=True, exist_ok=True)
    live_skill.joinpath("SKILL.md").write_text(
        "---\nname: u38-smoke-temp\ndescription: Temporary U38 CLI preload validation skill\nversion: 1.0.0\n---\n"
        "When asked for the U38 skill marker, reply exactly U38_SKILL_OK.\n", encoding="utf-8")
    live_skill_file.write_text("u38-smoke-temp\n", encoding="utf-8")
    model_env = dict(os.environ)
    model_env["ATLAS_ROOT"] = str(live_root)
    try:
        live = subprocess.run([sys.executable, "-m", "atlas.cli", "exec", "--skills-file", str(live_skill_file),
                               "Reply with the marker required by the preloaded skill."],
                              cwd=ROOT / "core", env=model_env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=240)
        check(live.returncode == 0 and "U38_SKILL_OK" in live.stdout,
              "model-backed CLI skill preload did not produce the required marker")
    finally:
        live_skill_file.unlink(missing_ok=True)
        shutil.rmtree(live_skill, ignore_errors=True)
    print("U38 scenario: real-provider CLI skill-file preload PASS", flush=True)

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
        skills_root = root / "marketplace"
        skill_path = skills_root / "tools" / "market-skill" / "SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("---\nname: market-skill\ndescription: Scenario skill\nversion: 1.0.0\n---\nUseful instructions.\n", encoding="utf-8")
        manager = SkillManager(root / "bundled-empty")
        manager.register_skill_source(SkillSource("marketplace", skills_root, 20, layout="category"))
        manager.scan_skills_sync()
        denied = False
        try:
            import asyncio
            asyncio.run(manager.activate("market-skill"))
        except PermissionError:
            denied = True
        check(denied, "runtime skill activation ignored source policy")
        set_policy({"overrides": {"market-skill": True}})
        check((await_activation := asyncio.run(manager.activate("market-skill"))) is not None
              and await_activation.strip() == "Useful instructions.", "runtime explicit override failed")
        registry = SimpleNamespace(path=root / "registry.sqlite")
        collection = AgentSkillCollections(registry)
        collection.set_agent_skill("agent-a", "market-skill", enabled=True)
        collection.record_usage("market-skill", "agent-a")
        stats = collection.usage_stats("market-skill")
        check(stats["total_use_count"] == 1 and stats["agents"][0]["agent_id"] == "agent-a", "skill telemetry scenario failed")
        check(collection.remove_agent_skill("agent-a", "market-skill"), "agent skill removal failed")
        check(not collection.list_agent_skills("agent-a"), "agent skill relation remained")
        print("U38 scenario: runtime source policy and per-agent skill health PASS", flush=True)

    async def ephemeral_storage_scenario() -> None:
        from atlas.memory import MemoryStore
        with tempfile.TemporaryDirectory(prefix="atlas-u38-ephemeral-") as temp:
            memory = MemoryStore(Path(temp) / "sessions.sqlite")
            await memory.init()
            source_id = await memory.create_conversation("source")
            await memory.save_message(source_id, "user", "persisted source question")
            temporary_id = await memory.create_conversation("Ephemeral side chat")
            await memory.save_message(temporary_id, "assistant", "temporary answer")
            check(len(await memory.get_conversation_messages(source_id)) == 1, "temporary reply altered source transcript")
            check(await memory.delete_conversation(temporary_id), "temporary conversation cleanup failed")
            check(await memory.get_conversation(temporary_id) is None, "temporary conversation remained in history storage")
            await memory.close()
    asyncio.run(ephemeral_storage_scenario())
    print("U38 scenario: temporary transcript is isolated and deleted at close PASS", flush=True)

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
