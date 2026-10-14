"""Environment-only credential access for the narrow ported tool boundary.

Atlas' provider configuration owns persistent secrets. These helpers intentionally
do not synthesize a routed profile scope from process-global environment state.
"""
from __future__ import annotations

import os


def get_secret(name: str, default=None):
    return os.environ.get(name, default)


def current_secret_scope():
    return None


def serves_routed_profile() -> bool:
    return False

