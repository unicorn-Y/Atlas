"""Atlas engine: one package holding the runtime, the agent core, and the kernel.

Layout:
  ``atlas.engine``            adapters and runtime wiring (``AtlasRuntime``, policy,
                              permissions, session sync)
  ``atlas.engine.agent``      ported agent core (state, messages, compression)
  ``atlas.engine.tools``      ported tool engine and environment backends
  ``atlas.engine.kernel``     the turn loop, prompt assembly, tool dispatch
  ``atlas.engine.state``      durable session storage (``SessionDB``)

``AtlasRuntime`` is exported lazily: importing it eagerly pulled the whole
runtime graph into every process that merely touched ``atlas.engine``, which
defeated deferred startup. PEP 562 keeps ``from atlas.engine import
AtlasRuntime`` working without the import cost.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

__all__ = ["AtlasRuntime", "config", "goals"]


def __getattr__(name: str) -> object:
    if name == "AtlasRuntime":
        module = import_module(".atlas_runtime", __name__)
        value = module.AtlasRuntime
        globals()[name] = value
        return value
    if name in {"config", "goals"}:
        module: ModuleType = import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
