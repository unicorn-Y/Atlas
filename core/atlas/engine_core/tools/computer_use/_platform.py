"""Small platform flags needed when spawning the optional CUA driver (MIT port)."""
from __future__ import annotations

import subprocess


def windows_hide_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))



