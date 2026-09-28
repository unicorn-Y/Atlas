"""ZCode app-server protocol entry point."""

from atlas.runtime.external_process import ExternalProcessAdapter


def create() -> ExternalProcessAdapter:
    return ExternalProcessAdapter("zcode", "zcode", ["app-server"])
