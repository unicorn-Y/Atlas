"""Small backend command-line predicate needed by SessionDB recovery metadata."""

from __future__ import annotations


def _is_ephemeral_port_zero_backend(argv: list[str]) -> bool:
    if not any(str(token) in {"serve", "dashboard"} for token in argv):
        return False
    return any(
        (str(token) == "--port" and index + 1 < len(argv) and str(argv[index + 1]) == "0")
        or str(token).startswith("--port=") and str(token).split("=", 1)[1].strip() == "0"
        for index, token in enumerate(argv)
    )
