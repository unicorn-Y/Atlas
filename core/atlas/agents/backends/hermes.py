"""Atlas' ACP protocol entry point for the Hermes external agent."""

from __future__ import annotations

from atlas.runtime.backends import ACPBackend

# ``hermes acp`` asks for shell-hook confirmation on a TTY when it meets an
# unseen hook. Under ACP there is no TTY, so the handshake blocks forever and the
# session never opens. ``--accept-hooks`` is the documented non-interactive
# equivalent (HERMES_ACCEPT_HOOKS=1) and only covers Atlas' own hook set.
_ARGS = ["acp", "--accept-hooks"]


def create() -> ACPBackend:
    return ACPBackend("hermes", "hermes", list(_ARGS))
