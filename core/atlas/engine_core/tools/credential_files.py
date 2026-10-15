"""Local browser snapshot path mapping for the Atlas-owned engine.

Hermes remote sandbox credential/cache mounts are not enabled in Atlas. Local
browser snapshots keep their host path; requesting that path from a remote
terminal backend fails explicitly rather than claiming a mount exists.
"""

from __future__ import annotations


def to_agent_visible_cache_path(host_path: str, container_base: str = "/root/.hermes") -> str:
    del container_base
    from atlas.tools.terminal_scope import terminal_env

    backend = terminal_env("TERMINAL_ENV", "local").strip().lower()
    if backend not in {"", "local"}:
        raise RuntimeError("Atlas does not support mounting browser snapshot cache paths into remote terminal backends.")
    return str(host_path)


def _remote_mounts_unsupported(*args, **kwargs):
    del args, kwargs
    raise RuntimeError("Atlas does not support mounting Hermes credential, skill, or cache files into remote terminal backends.")


get_credential_file_mounts = _remote_mounts_unsupported
get_skills_directory_mount = _remote_mounts_unsupported
iter_cache_files = _remote_mounts_unsupported
iter_skills_files = _remote_mounts_unsupported
get_cache_directory_mounts = _remote_mounts_unsupported
