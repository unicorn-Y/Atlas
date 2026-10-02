"""C6A-R1: basedpyright fallback for the Python LSP adapter.

pyright is still preferred; when it is absent the same ``pyright`` server id
falls back to ``basedpyright-langserver`` / ``basedpyright`` (a drop-in fork),
and the missing hint says either install works.  Probing is monkeypatched —
no real language server is required or spawned.
"""
from __future__ import annotations

from pathlib import Path

from atlas.lsp.availability import missing_server_hint
from atlas.lsp.servers import ServerContext, _spawn_pyright


def _ctx(tmp_path: Path) -> ServerContext:
    return ServerContext(workspace_root=str(tmp_path), trusted=True)


def _patch_which(monkeypatch, **available: str) -> None:
    """``shutil.which`` stub: only the given names resolve, to the given paths."""

    def fake_which(name, path=None):
        return available.get(name)

    monkeypatch.setattr("atlas.lsp.availability.shutil.which", fake_which)


def test_basedpyright_langserver_used_when_pyright_missing(tmp_path, monkeypatch):
    langserver = tmp_path / "basedpyright-langserver.cmd"
    langserver.write_text("")
    _patch_which(monkeypatch, **{"basedpyright-langserver": str(langserver)})
    spec = _spawn_pyright(str(tmp_path), _ctx(tmp_path))
    assert spec is not None
    assert spec.command[0] == str(langserver)
    assert spec.command[1] == "--stdio"
    assert spec.workspace_root == str(tmp_path)


def test_basedpyright_cli_fallback_when_langserver_missing(tmp_path, monkeypatch):
    cli = tmp_path / "basedpyright.cmd"
    cli.write_text("")
    _patch_which(monkeypatch, **{"basedpyright": str(cli)})
    spec = _spawn_pyright(str(tmp_path), _ctx(tmp_path))
    assert spec is not None
    # No sibling on disk: the CLI itself stays a valid spawn spec (same rule as pyright CLI).
    assert spec.command[0] == str(cli)


def test_basedpyright_cli_resolves_existing_sibling(tmp_path, monkeypatch):
    cli = tmp_path / "basedpyright.cmd"
    cli.write_text("")
    sibling = tmp_path / "basedpyright-langserver.cmd"
    sibling.write_text("")
    _patch_which(monkeypatch, **{"basedpyright": str(cli)})
    spec = _spawn_pyright(str(tmp_path), _ctx(tmp_path))
    assert spec is not None
    assert spec.command[0] == str(sibling)


def test_pyright_priority_preserved_when_both_families_present(tmp_path, monkeypatch):
    pyright_ls = tmp_path / "pyright-langserver.cmd"
    pyright_ls.write_text("")
    based_ls = tmp_path / "basedpyright-langserver.cmd"
    based_ls.write_text("")
    _patch_which(monkeypatch, **{"pyright-langserver": str(pyright_ls),
                                 "basedpyright-langserver": str(based_ls)})
    spec = _spawn_pyright(str(tmp_path), _ctx(tmp_path))
    assert spec is not None
    assert spec.command[0] == str(pyright_ls)


def test_pyright_cli_still_beats_basedpyright_langserver(tmp_path, monkeypatch):
    pyright_cli = tmp_path / "pyright.cmd"
    pyright_cli.write_text("")
    based_ls = tmp_path / "basedpyright-langserver.cmd"
    based_ls.write_text("")
    _patch_which(monkeypatch, **{"pyright": str(pyright_cli),
                                 "basedpyright-langserver": str(based_ls)})
    spec = _spawn_pyright(str(tmp_path), _ctx(tmp_path))
    assert spec is not None
    assert spec.command[0] == str(pyright_cli)


def test_all_missing_yields_no_spec(tmp_path, monkeypatch):
    _patch_which(monkeypatch)
    assert _spawn_pyright(str(tmp_path), _ctx(tmp_path)) is None


def test_missing_hint_says_either_install_works():
    hint = missing_server_hint("pyright")
    assert "安装" in hint
    assert "pyright" in hint and "basedpyright" in hint
    assert "均可" in hint
