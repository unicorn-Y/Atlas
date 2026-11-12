"""The provider set, assembled in one place.

Each module in this package owns one subsystem's read-only answers. They are
imported here in presentation order; :func:`atlas.introspect.registry.providers`
returns this tuple, and nothing else in Atlas reads a provider module directly.

Heavy imports (the tool registry, the config loader) happen **inside** the call
sites rather than at module import time, so mounting the introspection router
never pulls a subsystem into a process that was not going to load it anyway.

The provider modules are imported as modules rather than through
``from ... import PROVIDER as x``: every module names its provider ``PROVIDER``,
so the rename is required, and ruff reads the resulting lower-case binding of an
upper-case constant as a mistake (N811). Binding the module and reading
``module.PROVIDER`` says the same thing without the false positive, and it keeps
the module available for a future provider that wants to expose helpers.
"""

from __future__ import annotations

from atlas.introspect.providers import (
    config,
    context,
    events,
    goals,
    governance,
    handlers,
    health,
    memory,
    models,
    services,
    skills,
    tools,
)

PROVIDERS = (
    services.PROVIDER,
    handlers.PROVIDER,
    tools.PROVIDER,
    events.PROVIDER,
    config.PROVIDER,
    health.PROVIDER,
    governance.PROVIDER,
    memory.PROVIDER,
    goals.PROVIDER,
    models.PROVIDER,
    skills.PROVIDER,
    context.PROVIDER,
)

__all__ = ["PROVIDERS"]
