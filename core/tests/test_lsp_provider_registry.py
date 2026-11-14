"""E30: unified LSP provider registry — register/query, by language and root."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.lsp.registry import LspProviderRegistry
from atlas.lsp.servers import SERVERS, ServerDef, language_id_for


def _stub_provider(server_id: str, exts: tuple[str, ...], language_id: str = "",
                   description: str = "stub") -> ServerDef:
    return ServerDef(server_id, exts, lambda fp, ws: ws, lambda root, ctx: None,
                     description=description, language_id=language_id)


@pytest.mark.unit
def test_seeded_registry_resolves_builtins_by_extension():
    registry = LspProviderRegistry.seed_defaults()
    assert registry.for_file("pkg/module.py").server_id == "pyright"
    assert registry.for_file("app/main.ts").server_id == "typescript"
    assert registry.for_file("notes.txt") is None
    # Built-ins are all present, exactly once, at the built-in priority.
    ids = [entry["server_id"] for entry in registry.providers()]
    assert len(ids) == len({s.server_id for s in SERVERS})
    assert set(ids) == {s.server_id for s in SERVERS}
    assert registry.handles_extension(".py") is True
    assert registry.handles_extension(".txt") is False


@pytest.mark.unit
def test_config_declared_server_wins_over_builtin():
    """Mirrors LSPService._server_for: lsp.servers entries claim extensions first."""
    extra = _stub_provider("my-ts", (".ts",), language_id="typescript")
    registry = LspProviderRegistry.seed_defaults([extra])
    assert registry.for_file("app/main.ts").server_id == "my-ts"
    # Python still resolves to the built-in.
    assert registry.for_file("pkg/module.py").server_id == "pyright"


@pytest.mark.unit
def test_root_scoped_provider_wins_inside_its_root_only(tmp_path: Path):
    registry = LspProviderRegistry.seed_defaults()
    root_a = tmp_path / "proj-a"
    root_b = tmp_path / "proj-b"
    root_a.mkdir()
    root_b.mkdir()
    scoped = _stub_provider("scoped-py", (".py",), language_id="python")
    registry.register(scoped, root=str(root_a), priority=0)
    inside = registry.for_file(str(root_a / "pkg" / "m.py"))
    outside = registry.for_file(str(root_b / "m.py"))
    assert inside is not None and inside.server_id == "scoped-py"
    # Longest matching root wins; other trees keep the built-in.
    assert outside.server_id == "pyright"


@pytest.mark.unit
def test_longest_root_wins_between_two_scoped_entries(tmp_path: Path):
    outer = tmp_path / "monorepo"
    inner = outer / "packages" / "web"
    inner.mkdir(parents=True)
    outer_server = _stub_provider("outer", (".ts",))
    inner_server = _stub_provider("inner", (".ts",))
    registry = LspProviderRegistry()
    registry.register(outer_server, root=str(outer))
    registry.register(inner_server, root=str(inner))
    assert registry.for_file(str(inner / "index.ts")).server_id == "inner"
    assert registry.for_file(str(outer / "scripts" / "build.ts")).server_id == "outer"


@pytest.mark.unit
def test_by_language_returns_explicit_language_registrations():
    registry = LspProviderRegistry.seed_defaults()
    custom = _stub_provider("nix-lsp", (".nix",), language_id="nix")
    registry.register(custom)
    found = registry.by_language("nix")
    assert [p.server_id for p in found] == ["nix-lsp"]
    # Built-ins derive their languageId from the extension table; they are not
    # "explicitly registered for a language" and must not appear here.
    assert registry.by_language("python") == []
    assert registry.by_language("") == []


@pytest.mark.unit
def test_unregister_removes_by_id_and_optional_root(tmp_path: Path):
    registry = LspProviderRegistry()
    scoped = _stub_provider("scoped", (".py",))
    registry.register(scoped, root=str(tmp_path))
    assert registry.unregister("scoped") == 1
    assert registry.for_file(str(tmp_path / "m.py")) is None
    assert registry.unregister("scoped") == 0
    # Registration validation: not a ServerDef / negative priority fail fast.
    with pytest.raises(TypeError):
        registry.register({"server_id": "not-a-def"})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        registry.register(_stub_provider("x", (".py",)), priority=-1)


@pytest.mark.unit
def test_service_server_for_resolves_through_the_registry(tmp_path: Path):
    """LSPService._server_for now delegates to the unified provider registry."""
    from atlas.lsp.manager import LSPService

    service = LSPService(enabled=False)
    assert service._server_for("pkg/module.py").server_id == "pyright"
    # A root-scoped runtime registration wins inside that root.
    custom = _stub_provider("embedder", (".py",))
    service.register_provider(custom, root=str(tmp_path), priority=0)
    assert service._server_for(str(tmp_path / "m.py")).server_id == "embedder"
    assert service._server_for("pkg/module.py").server_id == "pyright"
    assert service.unregister_provider("embedder", root=str(tmp_path)) == 1
    assert service._server_for(str(tmp_path / "m.py")).server_id == "pyright"


@pytest.mark.unit
def test_language_id_for_still_derives_for_builtin_ids():
    registry = LspProviderRegistry.seed_defaults()
    resolved = registry.for_file("app/main.ts")
    assert language_id_for("app/main.ts", resolved) == "typescript"
