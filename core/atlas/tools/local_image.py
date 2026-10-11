# Behavior reference: openai/codex@de8fab6d7adfcef8b4ce6f02f3b5c8be4092015a,
# codex-rs/core/src/tools/handlers/view_image.rs (Apache-2.0); independent adapter.
"""Read a workspace image and attach it to the following model turn."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from typing import Any


MAX_IMAGE_BYTES = 20 * 1024 * 1024

# file signature -> mime. Checked before the extension guess so a mislabeled
# file cannot smuggle a non-image payload into a ``data:`` URL.
_MAGIC_MIME = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def _sniff_mime(payload: bytes, fallback: str) -> str:
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    if len(payload) >= 12 and payload[4:12] == b"ftypavif":
        return "image/avif"
    for signature, mime in _MAGIC_MIME:
        if payload.startswith(signature):
            return mime
    return fallback


def _probe_dimensions(payload: bytes) -> tuple[int | None, int | None, str | None]:
    """Return (width, height, format) from the decoded header, never raising."""
    try:
        from PIL import Image  # noqa: PLC0415 - optional dependency, probe lazily

        with Image.open(io.BytesIO(payload)) as probe:
            width, height = probe.size
            return int(width), int(height), str(probe.format or "").upper() or None
    except Exception:  # noqa: BLE001 - missing PIL or a corrupt header is reported as unknown
        return None, None, None


def view_workspace_image(workspace: str, path: str, detail: str = "auto") -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    image_path = (root / path).resolve()
    try:
        image_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Image path must remain inside the active workspace.") from exc
    if not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    guessed = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    payload = image_path.read_bytes()
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 20 MiB input limit.")
    mime_type = _sniff_mime(payload, guessed)
    if not mime_type.startswith("image/"):
        raise ValueError(
            f"view_image accepts image files only; {image_path.name} looks like {guessed}."
        )
    width, height, image_format = _probe_dimensions(payload)
    url = f"data:{mime_type};base64,{base64.b64encode(payload).decode('ascii')}"
    shape = f"{width}x{height}" if width and height else "unknown size"
    return {
        "content": [{
            "type": "text",
            "text": (
                f"Attached {image_path.name} ({mime_type}, {shape}, "
                f"{len(payload)} bytes, detail={detail})."
            ),
        }],
        "data": {
            "path": str(image_path), "mimeType": mime_type, "format": image_format,
            "width": width, "height": height,
            "size": len(payload), "detail": detail, "_image_data_url": url,
        },
    }
