"""Thin adapters for external Agent runtimes."""

from atlas.agents.backends import claude, codex, hermes, pi, zcode


def create_backends() -> dict[str, object]:
    """Build inactive backend adapters; no process starts until a caller connects."""
    return {
        "codex": codex.create(),
        "claude": claude.create(),
        "hermes": hermes.create(),
        "pi": pi.create(),
        "zcode": zcode.create(),
    }


__all__ = ["claude", "codex", "create_backends", "hermes", "pi", "zcode"]
