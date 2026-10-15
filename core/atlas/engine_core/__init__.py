"""Atlas-owned Hermes runtime package with lazy module exports."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

__all__ = ["config", "goals"]


def __getattr__(name: str) -> ModuleType:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{name}", __name__)
    globals()[name] = module
    return module
