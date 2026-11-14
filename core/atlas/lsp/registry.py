# Behavior reference: DSH parity ledger E30 — "LSP 四操作闭合联合 + provider registry".
# This is Atlas' unified LSP provider registry: one register/query point over the
# language servers the operation surface (``lsp_*`` model tools) resolves through.
# It does not spawn processes and never touches the network; it only answers
# "which provider handles this file, at which root".
"""Unified LSP provider registry (registration and query, by language and root).

The registry is the single place that maps a file (and optionally a workspace
root) to a language-server provider.  :class:`atlas.lsp.manager.LSPService`
seeds it with the built-in servers and the ``lsp.servers`` config entries
(config-declared entries win, mirroring the previous ``_server_for`` order),
and the ``lsp_*`` model tools reach it through ``LSPService._server_for``.

Root-scoped registrations let a caller pin a provider to one workspace tree
(longest matching root wins over global entries); they are how tests and
embedders can stand in a fake server for one project without touching the
global catalog.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from atlas.lsp.servers import SERVERS, ServerDef, find_server_for_file

__all__ = ["LspProviderRegistry"]


class LspProviderRegistry:
    """Register / query language-server providers, by extension (language) and root.

    Query semantics (``for_file``):

    1. Root-scoped providers whose registered root is an ancestor of the file:
       the longest matching root wins; among entries on the same root the
       lowest ``priority`` (highest precedence) then the earliest registration
       wins.
    2. Global providers in ``(priority, registration order)`` order, matched by
       extension — the same "first match wins" rule the built-in list uses.

    The registry never spawns anything: resolution only, so a mis-registered
    entry cannot start a process.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._counter = 0

    # ---- registration ----

    def register(
        self, provider: ServerDef, *, root: str | None = None, priority: int = 50,
    ) -> None:
        """Add ``provider``; ``root`` scopes it to files under that directory.

        Lower ``priority`` wins ties; built-ins register at 50, config-declared
        servers at 10 (config may claim an extension ahead of a built-in).
        """
        if not isinstance(provider, ServerDef):
            raise TypeError("provider must be an atlas.lsp.servers.ServerDef")
        if priority < 0:
            raise ValueError("priority must be non-negative")
        normalized_root = ""
        if root is not None:
            normalized_root = str(Path(root).expanduser().resolve())
        with self._lock:
            self._counter += 1
            self._entries.append({
                "order": self._counter,
                "priority": int(priority),
                "root": normalized_root,
                "provider": provider,
            })

    def unregister(self, server_id: str, *, root: str | None = None) -> int:
        """Remove every registration naming ``server_id`` (optionally only at ``root``).

        Returns how many entries were removed; unknown ids remove nothing.
        """
        normalized_root = ""
        if root is not None:
            normalized_root = str(Path(root).expanduser().resolve())
        with self._lock:
            before = len(self._entries)
            self._entries = [
                entry for entry in self._entries
                if not (
                    entry["provider"].server_id == server_id
                    and (root is None or entry["root"] == normalized_root)
                )
            ]
            return before - len(self._entries)

    # ---- query ----

    def for_file(self, file_path: str) -> Optional[ServerDef]:
        """The provider that handles ``file_path``, or ``None``.

        Resolution is pure (extension + path-prefix matching) and mirrors the
        previous ``LSPService._server_for`` result for the seeded catalog.
        """
        path = str(file_path or "")
        if not path:
            return None
        with self._lock:
            entries = list(self._entries)
        resolved = str(Path(path).resolve())
        scoped = [
            entry for entry in entries
            if entry["root"] and _is_under(resolved, entry["root"])
            and entry["provider"].matches(path)
        ]
        if scoped:
            scoped.sort(key=lambda entry: (-len(entry["root"]), entry["priority"], entry["order"]))
            return scoped[0]["provider"]
        global_entries = [entry for entry in entries if not entry["root"]]
        global_entries.sort(key=lambda entry: (entry["priority"], entry["order"]))
        for entry in global_entries:
            if entry["provider"].matches(path):
                return entry["provider"]
        return None

    def by_language(self, language_id: str) -> list[ServerDef]:
        """Every registered provider whose ``language_id`` names ``language_id``.

        Built-ins mostly derive their languageId from the extension table, so
        an empty ``language_id`` field means "derived"; those are not returned
        here — this answers "what did someone explicitly register for X".
        """
        wanted = str(language_id or "").strip().lower()
        if not wanted:
            return []
        with self._lock:
            entries = list(self._entries)
        seen: dict[str, ServerDef] = {}
        for entry in entries:
            provider = entry["provider"]
            if provider.language_id and provider.language_id.lower() == wanted:
                seen.setdefault(provider.server_id, provider)
        return list(seen.values())

    def providers(self) -> list[dict[str, Any]]:
        """A stable snapshot of the catalog (``server_id``, extensions, root, priority)."""
        with self._lock:
            entries = list(self._entries)
        entries.sort(key=lambda entry: (entry["priority"], entry["order"]))
        return [
            {
                "server_id": entry["provider"].server_id,
                "extensions": list(entry["provider"].extensions),
                "description": entry["provider"].description,
                "root": entry["root"] or None,
                "priority": entry["priority"],
                "language_id": entry["provider"].language_id,
            }
            for entry in entries
        ]

    def handles_extension(self, ext: str) -> bool:
        """True iff any registered provider claims ``ext`` (pre-write capture decision)."""
        wanted = str(ext or "").lower()
        if not wanted:
            return False
        with self._lock:
            entries = list(self._entries)
        return any(wanted in entry["provider"].extensions for entry in entries)

    # ---- seeding ----

    @classmethod
    def seed_defaults(cls, extra_servers: Optional[list[ServerDef]] = None) -> "LspProviderRegistry":
        """Built-ins first, then config-declared servers ahead of them (config wins)."""
        registry = cls()
        for server in SERVERS:
            registry.register(server, priority=50)
        for server in reversed(list(extra_servers or [])):
            # Later config entries register earlier so first-declared wins ties.
            registry.register(server, priority=10)
        return registry


def _is_under(path: str, root: str) -> bool:
    """Pure prefix containment (no filesystem access): ``root`` is an ancestor of ``path``."""
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False
