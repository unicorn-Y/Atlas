"""Atlas self-introspection: read-only views over the running system.

The public entry point is :mod:`atlas.introspect.registry`. This module only
assembles the provider tuple so that ``registry.providers()`` has one place to
import from.
"""

from __future__ import annotations

from atlas.introspect.providers import PROVIDERS

__all__ = ["PROVIDERS"]
