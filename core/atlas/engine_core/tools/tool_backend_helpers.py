"""Minimal backend-selection messages used by Atlas' browser adapter (MIT source seam)."""


def normalize_browser_cloud_provider(value: object | None) -> str:
    return str(value or "auto").strip().lower() or "auto"


def selection_error(section: str, selection_name: str, failure: str) -> str:
    return f"{section} is configured to use {selection_name}, but {failure}."

