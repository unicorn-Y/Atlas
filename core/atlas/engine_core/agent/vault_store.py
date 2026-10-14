"""Origin normalization used to identify browser dialog targets."""
from urllib.parse import urlsplit


def normalize_origin(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" if parsed.scheme and parsed.netloc else ""

