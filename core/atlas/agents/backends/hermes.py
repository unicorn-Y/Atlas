"""Hermes external process entry point."""

from atlas.runtime.external_process import ExternalProcessAdapter


def create() -> ExternalProcessAdapter:
    return ExternalProcessAdapter("hermes", "hermes", ["--cli", "chat"])
