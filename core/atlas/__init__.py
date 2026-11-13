"""Atlas - All-in-one AI Personal Assistant."""

import os
import types
from pathlib import Path


def _repair_no_proxy_ipv6() -> None:
    """Strip brackets from IPv6 literals in NO_PROXY before httpx ever reads it.

    curl accepts ``NO_PROXY=[::1]``; httpx does not. httpx validates each entry
    with ``is_ipv6_hostname``, which returns False for the bracketed form, so the
    entry falls through to the generic domain branch and becomes the mount key
    ``all://*[::1]`` — not a valid URL. Every ``httpx.Client()`` then raises
    ``InvalidURL: Invalid port: ':1]'`` from its constructor, so *all* model
    requests die before any I/O, and the error names a port nobody configured.
    That misdirection sends every investigation into the wrong layer.

    Done at package import because httpx clients are built in many modules
    (router, routes, models_dev, network_transport) and by third-party code; a
    per-call-site fix would keep missing new ones. The rewrite is semantically
    identical, so it is applied to the process environment without a prompt.
    """
    import re

    bracketed = re.compile(r"^\[(?P<inner>[0-9A-Fa-f:.]+)\](?::(?P<port>\d+))?$")
    for name in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(name)
        if not raw or "[" not in raw:
            continue
        fixed: list[str] = []
        for raw_entry in raw.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            match = bracketed.match(entry)
            if match:
                port = match.group("port")
                fixed.append(f"{match.group('inner')}:{port}" if port else match.group("inner"))
            else:
                fixed.append(entry)
        os.environ[name] = ",".join(fixed)


# CPython's Windows SQLite DLL may lag behind the runtime shipped with Atlas.
# Add the verified, app-local DLL directory before importing sqlite3 anywhere
# in Atlas so the stdlib extension binds to the same fixed runtime as releases.
_sqlite_dll_handle = None
_sqlite_dll_directory = None
if os.name == "nt":
    _sqlite_runtime = Path(__file__).with_name("_vendor")
    _sqlite_dll = _sqlite_runtime / "sqlite3.dll"
    if _sqlite_dll.is_file():
        import ctypes

        _sqlite_dll_handle = ctypes.WinDLL(str(_sqlite_dll))
        _sqlite_dll_directory = os.add_dll_directory(str(_sqlite_runtime))

_repair_no_proxy_ipv6()


def _install_legacy_hermes_aliases() -> None:
    """Map retired ``hermes_*`` module names onto their ``atlas_*`` successors.

    The engine modules were renamed because Atlas owns this code; the old names
    were only kept for the source migration. Imports from outside this checkout
    (installed plugins, operator scripts, older tests) may still say
    ``hermes_state``, so resolve them instead of breaking them.

    A meta-path finder rather than eager ``sys.modules`` writes: eagerly importing
    forty engine modules here would pull the whole state layer into every process
    that merely touches ``atlas``, which defeats the deferred-startup work.
    """
    import importlib.abc
    import importlib.util
    import sys

    renames = {
        "atlas.engine.state.hermes_": "atlas.engine.state.atlas_",
        # hermes_constants sits at the engine root, not under state/.
        "atlas.engine.hermes_": "atlas.engine.atlas_",
        "atlas.safety.hermes_": "atlas.safety.atlas_",
        "atlas.tools.x2.hermes_": "atlas.tools.x2.atlas_",
    }

    # Bare top-level names. The engine used to be imported as ``hermes_state``,
    # ``hermes_constants`` and so on, with no ``atlas.`` prefix at all; the old
    # finder only rewrote qualified ``atlas.*.hermes_*`` names, so those imports
    # failed outright. Ten tests in ``test_atlas_session_sync.py`` were failing on
    # ``ModuleNotFoundError: No module named 'hermes_state'`` for exactly this
    # reason, and any installed plugin still importing the old way breaks too.
    bare_renames = {
        "hermes_state": "atlas.engine.state.atlas_state",
        "hermes_state_messages": "atlas.engine.state.atlas_state_messages",
        "hermes_state_schema": "atlas.engine.state.atlas_state_schema",
        "hermes_state_common": "atlas.engine.state.atlas_state_common",
        "hermes_state_search": "atlas.engine.state.atlas_state_search",
        "hermes_state_timeline": "atlas.engine.state.atlas_state_timeline",
        "hermes_state_errors": "atlas.engine.state.atlas_state_errors",
        "hermes_state_holders": "atlas.engine.state.atlas_state_holders",
        "hermes_state_fts": "atlas.engine.state.atlas_state_fts",
        "hermes_state_titles": "atlas.engine.state.atlas_state_titles",
        "hermes_state_portability": "atlas.engine.state.atlas_state_portability",
        "hermes_constants": "atlas.engine.atlas_constants",
        "hermes_time": "atlas.engine.state.timefmt",
        # The old CLI package only matters for the one symbol tests patch; a bare
        # "hermes_cli" -> "atlas" entry would alias the package object to this very
        # module and make every submodule import fail, so only real names are listed.
        "hermes_cli.goals": "atlas.engine.goals",
        "hermes_runtime": "atlas.engine.atlas_runtime",
        "hermes_policy": "atlas.engine.atlas_policy",
    }

    #: Retired top-level packages. These get a real (empty) package object rather
    #: than a direct alias, because ``monkeypatch.setattr("hermes_cli.goals.X")``
    #: and ``import hermes_cli.foo`` both require the parent package to import.
    #: Aliasing the package itself onto ``atlas`` would not work: it would make
    #: ``hermes_cli.<anything>`` resolve against Atlas's own namespace, so a typo
    #: would silently patch the wrong object instead of failing.
    legacy_packages = {"hermes_cli": "atlas"}

    class _LegacyHermesFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            package = legacy_packages.get(fullname)
            if package is not None:
                return importlib.util.spec_from_loader(
                    fullname, loader=_NamespacePackageLoader(fullname))
            exact = bare_renames.get(fullname)
            if exact is not None:
                try:
                    module = importlib.import_module(exact)
                except ImportError:
                    return None
                sys.modules[fullname] = module
                return importlib.util.spec_from_loader(
                    fullname, loader=_AliasLoader(module))
            for old, new in renames.items():
                if fullname.startswith(old):
                    successor = new + fullname[len(old):]
                    try:
                        module = importlib.import_module(successor)
                    except ImportError:
                        return None
                    sys.modules[fullname] = module
                    return importlib.util.spec_from_loader(
                        fullname, loader=_AliasLoader(module))
            return None

    class _AliasLoader(importlib.abc.Loader):
        def __init__(self, module):
            self._module = module

        def create_module(self, spec):
            return self._module

        def exec_module(self, module):
            return None

    class _NamespacePackageLoader(importlib.abc.Loader):
        """An empty package whose ``__path__`` is empty, so only explicit
        submodule aliases from ``bare_renames`` can resolve beneath it."""

        def __init__(self, name: str):
            self._name = name

        def create_module(self, spec):
            module = types.ModuleType(self._name)
            module.__path__ = []  # a package, but with nothing on the filesystem
            return module

        def exec_module(self, module):
            return None

    if not any(isinstance(f, _LegacyHermesFinder) for f in sys.meta_path):
        sys.meta_path.append(_LegacyHermesFinder())


_install_legacy_hermes_aliases()

__version__ = "0.1.0"
