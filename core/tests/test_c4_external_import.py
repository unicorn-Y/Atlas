"""E6 import tests — fake .claude / .codex homes only.

Every call passes explicit ``source_home`` / ``atlas_home`` roots, so the real
``~/.claude`` and ``~/.codex`` are never touched. Source trees are hashed
before and after import to prove the zero-write guarantee.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from atlas.runtime.external_import import import_external, scan_external
from atlas.runtime.hooks import HookStore

ITEM_KEYS = {"kind", "name", "path", "action", "conflict", "detail"}


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _by_kind(items: list[dict], kind: str) -> list[dict]:
    return [item for item in items if item["kind"] == kind]


@pytest.fixture
def claude_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    claude = home / ".claude"
    _write(claude / "settings.json", json.dumps({
        "model": "sonnet",
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "echo pre", "timeout": 30},
            ]}],
            "SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}],
            "Notification": [{"hooks": [{"type": "command", "command": "echo notify"}]}],
        },
    }, ensure_ascii=False))
    _write(home / ".claude.json", json.dumps({"mcpServers": {
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                       "env": {"FORCE": "1"}},
    }}))
    _write(claude / "CLAUDE.md", "# 全局规则\n\n使用中文回复。\n")
    _write(claude / "skills" / "pdf" / "SKILL.md",
           "---\nname: pdf\ndescription: PDF 处理\n---\nPDF body\n")
    _write(claude / "agents" / "reviewer.md",
           "---\nname: reviewer\ndescription: 评审\n---\nYou review.\n")
    _write(claude / "commands" / "deploy.md", "---\ndescription: 部署\n---\ndeploy $ARGUMENTS\n")
    _write(claude / "projects" / "-tmp-ws" / "s1.jsonl", '{"type": "user"}\n')
    return home


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    home = tmp_path / "codex-home"
    codex = home / ".codex"
    _write(codex / "config.toml",
           'model = "gpt-5.2"\n\n[mcp_servers.docs]\ncommand = "uvx"\n'
           'args = ["mcp-server-docs"]\nenv = { DOCS_KEY = "x" }\n')
    _write(codex / "AGENTS.md", "# Codex 全局规则\n\n先写测试。\n")
    _write(codex / "prompts" / "review.md",
           "---\ndescription: 评审提示词\n---\nReview $ARGUMENTS\n")
    _write(codex / "agents" / "scout.toml", 'name = "scout"\ndescription = "侦察"\n')
    _write(codex / "sessions" / "2026" / "rollout-1.jsonl", '{"type": "session"}\n')
    _write(codex / "history.jsonl", "echo hello\n")
    return home


@pytest.fixture
def atlas_root(tmp_path: Path) -> Path:
    root = tmp_path / "atlas"
    root.mkdir()
    return root


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    _write(ws / "CLAUDE.md", "# 项目规则\n\n始终用中文。\n")
    return ws


def test_scan_claude_manifest_kinds_conflicts_and_item_shape(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    _write(atlas_root / "config" / "atlas.toml",
           '[tools.servers."filesystem"]\ncommand = "node"\nargs = ["old.js"]\n')
    _write(atlas_root / "skills" / "pdf" / "SKILL.md",
           "---\nname: pdf\ndescription: 不同的旧技能\n---\nold\n")

    scan = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                         source_home=claude_home)
    assert scan["source"] == "claude"
    assert str(claude_home / ".claude.json") in scan["sources"]

    kinds = {item["kind"] for item in scan["items"]}
    assert kinds == {"mcp", "hooks", "rules", "skills", "agents", "commands",
                     "model_prefs", "history"}
    assert all(set(item) == ITEM_KEYS for item in scan["items"])
    assert all(Path(item["path"]).is_absolute() for item in scan["items"])

    mcp = _by_kind(scan["items"], "mcp")
    assert len(mcp) == 1 and mcp[0]["name"] == "filesystem"
    assert mcp[0]["action"] == "skip" and mcp[0]["conflict"] is True

    skills = _by_kind(scan["items"], "skills")
    assert len(skills) == 1 and skills[0]["name"] == "pdf"
    assert skills[0]["action"] == "skip" and skills[0]["conflict"] is True

    hooks = _by_kind(scan["items"], "hooks")
    assert len(hooks) == 1 and hooks[0]["action"] == "import"

    rules = _by_kind(scan["items"], "rules")
    assert {item["name"] for item in rules} == {"CLAUDE.md（项目级）", "CLAUDE.md（用户级）"}

    agents = _by_kind(scan["items"], "agents")
    commands = _by_kind(scan["items"], "commands")
    assert agents[0]["name"] == "reviewer" and agents[0]["action"] == "import"
    assert commands[0]["name"] == "deploy" and commands[0]["action"] == "import"

    model = _by_kind(scan["items"], "model_prefs")
    assert len(model) == 1 and model[0]["action"] == "import"

    history = _by_kind(scan["items"], "history")
    assert len(history) == 1
    assert history[0]["action"] == "skip" and "只读历史" in history[0]["detail"]


def test_scan_codex_manifest_kinds(claude_home: Path, codex_home: Path,
                                   atlas_root: Path, workspace: Path) -> None:
    scan = scan_external("codex", workspace=workspace, atlas_home=atlas_root,
                         source_home=codex_home)
    assert scan["sources"] == [str(codex_home / ".codex")]

    kinds = {item["kind"] for item in scan["items"]}
    assert kinds == {"mcp", "rules", "commands", "agents", "model_prefs", "history"}

    mcp = _by_kind(scan["items"], "mcp")
    assert mcp[0]["name"] == "docs" and mcp[0]["action"] == "import"

    agents = _by_kind(scan["items"], "agents")
    assert agents[0]["name"] == "scout" and agents[0]["action"] == "skip"
    assert "直接读取" in agents[0]["detail"]

    history = _by_kind(scan["items"], "history")
    assert len(history) == 2 and all(item["action"] == "skip" for item in history)

    model = _by_kind(scan["items"], "model_prefs")
    assert model[0]["action"] == "import"


def test_import_claude_full_lands_everywhere_and_sources_untouched(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    _write(atlas_root / "config" / "atlas.toml", '[tools]\nauto_start = ["docs"]\n')
    hash_home = _tree_hash(claude_home)
    # The workspace source files must stay untouched; AGENTS.md is the import
    # target and is expected to change.
    claude_md_hash = _tree_hash(workspace / "CLAUDE.md")

    scan = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                         source_home=claude_home)
    selected = [item for item in scan["items"] if item["action"] != "skip"]
    result = import_external("claude", scan["items"], workspace=workspace,
                             atlas_home=atlas_root, source_home=claude_home)

    assert result["imported"] == len(selected)
    assert result["skipped"] == len(scan["items"]) - len(selected)
    assert "已导入" in result["report"] and "MCP 服务器 1 个" in result["report"]

    config = tomllib.loads((atlas_root / "config" / "atlas.toml").read_text(encoding="utf-8"))
    assert config["tools"]["servers"]["filesystem"]["command"] == "npx"
    assert config["tools"]["servers"]["filesystem"]["env"] == {"FORCE": "1"}
    assert config["tools"]["auto_start"] == ["docs", "filesystem"]

    hooks = HookStore(atlas_root / "data" / "hooks.toml").list()
    assert {(hook["event"], hook["command"]) for hook in hooks} == {
        ("tool.before", "echo pre"), ("run.started", "echo start"),
    }

    agents_md = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "始终用中文" in agents_md and "使用中文回复" in agents_md

    pdf_skill = atlas_root / "skills" / "pdf" / "SKILL.md"
    assert pdf_skill.read_text(encoding="utf-8").endswith("PDF body\n")
    assert (atlas_root / "data" / "commands" / "deploy.md").is_file()
    assert (atlas_root / "data" / "agents" / "reviewer.md").is_file()

    settings = json.loads((atlas_root / "data" / "user-settings.json").read_text(encoding="utf-8"))
    assert settings["selected_model"] == "sonnet"

    assert _tree_hash(claude_home) == hash_home
    assert _tree_hash(workspace / "CLAUDE.md") == claude_md_hash
    assert not (workspace / ".mcp.json").exists()


def test_reimport_after_full_import_is_a_noop(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    first = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                          source_home=claude_home)
    import_external("claude", first["items"], workspace=workspace,
                    atlas_home=atlas_root, source_home=claude_home)

    second = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                           source_home=claude_home)
    manifest_items = [item for item in second["items"] if item["kind"] != "history"]
    assert manifest_items and all(item["action"] == "skip" for item in manifest_items)

    again = import_external("claude", first["items"], workspace=workspace,
                            atlas_home=atlas_root, source_home=claude_home)
    assert again["imported"] == 0
    assert again["skipped"] == len(first["items"])


def test_conflicting_items_default_to_skip_and_forced_import_replaces(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    _write(atlas_root / "config" / "atlas.toml",
           '[tools.servers."filesystem"]\ncommand = "node"\nargs = ["old.js"]\n')
    old_skill = _write(atlas_root / "skills" / "pdf" / "SKILL.md",
                       "---\nname: pdf\ndescription: 旧版\n---\nold\n")

    scan = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                         source_home=claude_home)
    result = import_external("claude", scan["items"], workspace=workspace,
                             atlas_home=atlas_root, source_home=claude_home)
    assert all(not (item["conflict"] and item["action"] == "import") for item in scan["items"])
    assert old_skill.read_text(encoding="utf-8").endswith("old\n")
    config = tomllib.loads((atlas_root / "config" / "atlas.toml").read_text(encoding="utf-8"))
    assert config["tools"]["servers"]["filesystem"]["args"] == ["old.js"]
    assert result["skipped"] >= 2 and "同名冲突" in result["report"]

    forced = [dict(item, action="import") for item in scan["items"] if item["conflict"]]
    assert len(forced) == 2
    forced_result = import_external("claude", forced, workspace=workspace,
                                    atlas_home=atlas_root, source_home=claude_home)
    assert forced_result["imported"] == 2
    config = tomllib.loads((atlas_root / "config" / "atlas.toml").read_text(encoding="utf-8"))
    assert config["tools"]["servers"]["filesystem"]["command"] == "npx"
    pdf_skill = atlas_root / "skills" / "pdf" / "SKILL.md"
    assert pdf_skill.read_text(encoding="utf-8").endswith("PDF body\n")


def test_rules_merge_preserves_existing_agents_md(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    _write(workspace / "AGENTS.md", "# 我的规则\n\n自定义段落甲。\n")

    scan = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                         source_home=claude_home)
    rules = _by_kind(scan["items"], "rules")
    assert all(item["action"] == "merge" for item in rules)

    result = import_external("claude", rules, workspace=workspace,
                             atlas_home=atlas_root, source_home=claude_home)
    assert result["imported"] == 2

    merged = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert merged.startswith("# 我的规则")
    assert "自定义段落甲。" in merged
    assert "使用中文回复。" in merged and "始终用中文。" in merged

    again = import_external("claude", rules, workspace=workspace,
                            atlas_home=atlas_root, source_home=claude_home)
    assert again["imported"] == 0


def test_history_items_are_never_written(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    scan = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                         source_home=claude_home)
    result = import_external("claude", _by_kind(scan["items"], "history"),
                             workspace=workspace, atlas_home=atlas_root,
                             source_home=claude_home)
    assert result["imported"] == 0 and result["skipped"] >= 1
    assert not any("s1.jsonl" == path.name for path in atlas_root.rglob("*"))
    assert not (atlas_root / "projects").exists()


def test_codex_import_lands_mcp_rules_commands_model(
    codex_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    scan = scan_external("codex", workspace=workspace, atlas_home=atlas_root,
                         source_home=codex_home)
    result = import_external("codex", scan["items"], workspace=workspace,
                             atlas_home=atlas_root, source_home=codex_home)
    selected = [item for item in scan["items"] if item["action"] == "import"]
    assert result["imported"] == len(selected)

    config = tomllib.loads((atlas_root / "config" / "atlas.toml").read_text(encoding="utf-8"))
    assert config["tools"]["servers"]["docs"]["command"] == "uvx"
    assert config["tools"]["servers"]["docs"]["env"] == {"DOCS_KEY": "x"}
    assert "先写测试。" in (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert (atlas_root / "data" / "commands" / "review.md").is_file()
    settings = json.loads((atlas_root / "data" / "user-settings.json").read_text(encoding="utf-8"))
    assert settings["selected_model"] == "gpt-5.2"
    # Codex agents are read live by Atlas and history is read-only: none copied.
    assert not (atlas_root / "data" / "agents" / "scout.toml").exists()


def test_model_prefs_conflict_defaults_to_skip(
    claude_home: Path, atlas_root: Path, workspace: Path,
) -> None:
    _write(atlas_root / "data" / "user-settings.json",
           json.dumps({"selected_model": "claude-opus-4"}))

    scan = scan_external("claude", workspace=workspace, atlas_home=atlas_root,
                         source_home=claude_home)
    model = _by_kind(scan["items"], "model_prefs")
    assert model[0]["action"] == "skip" and model[0]["conflict"] is True

    result = import_external("claude", scan["items"], workspace=workspace,
                             atlas_home=atlas_root, source_home=claude_home)
    settings = json.loads((atlas_root / "data" / "user-settings.json").read_text(encoding="utf-8"))
    assert settings["selected_model"] == "claude-opus-4"
    assert result["skipped"] >= 1


def test_unknown_source_is_rejected(atlas_root: Path, workspace: Path) -> None:
    with pytest.raises(ValueError):
        scan_external("cursor", workspace=workspace, atlas_home=atlas_root)
    with pytest.raises(ValueError):
        import_external("cursor", [], workspace=workspace, atlas_home=atlas_root)
