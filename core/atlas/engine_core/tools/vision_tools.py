"""Image resize helper used by Atlas' image-to-model bridge.

Source: NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd (MIT).
Only the resize seam used by Atlas' tool result adapter is carried here.
"""
from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
_RESIZE_TARGET_BYTES = 5 * 1024 * 1024
_MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}


def _determine_mime_type(path: Path) -> str:
    return _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")


def _image_to_base64_data_url(path: Path, mime_type: Optional[str] = None) -> str:
    mime = mime_type or _determine_mime_type(path)
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _image_exceeds_dimension(path: Path, max_dimension: int) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as image:
            return max(image.size) > max_dimension
    except Exception:
        return False


def _resize_image_for_vision(image_path: Path, mime_type: Optional[str] = None,
                             max_base64_bytes: int = _RESIZE_TARGET_BYTES,
                             max_dimension: Optional[int] = None,
                             scale_out: Optional[dict] = None,
                             force_jpeg: bool = False) -> str:
    """Return a data URL, progressively shrinking it to the byte and dimension limits."""
    size = image_path.stat().st_size
    data_url = None
    if size * 4 // 3 + 100 <= max_base64_bytes and not (
        max_dimension is not None and _image_exceeds_dimension(image_path, max_dimension)
    ):
        data_url = _image_to_base64_data_url(image_path, mime_type)
        if len(data_url) <= max_base64_bytes:
            return data_url

    def raw() -> str:
        return data_url or _image_to_base64_data_url(image_path, mime_type)

    try:
        from PIL import Image
    except ImportError:
        return raw()
    try:
        image = Image.open(image_path)
    except Exception:
        return raw()
    is_png = (mime_type or _determine_mime_type(image_path)) == "image/png" and not force_jpeg
    fmt, out_mime = ("PNG", "image/png") if is_png else ("JPEG", "image/jpeg")
    if not is_png and image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    original = previous = (image.width, image.height)
    qualities = (None,) if is_png else (85, 70, 50)
    candidate = None
    for attempt in range(5):
        if attempt:
            width, height = max(int(image.width * .5), 64), max(int(image.height * .5), 64)
            if width == 64 and image.width > 0:
                height = max(int(image.height * (64 / image.width)), 64)
            elif height == 64 and image.height > 0:
                width = max(int(image.width * (64 / image.height)), 64)
            if (width, height) == previous:
                break
            image = image.resize((width, height), Image.LANCZOS)
            previous = width, height
        dims_ok = max_dimension is None or max(image.size) <= max_dimension
        for quality in qualities:
            buf = BytesIO()
            image.save(buf, format=fmt, **({} if quality is None else {"quality": quality}))
            candidate = f"data:{out_mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
            if len(candidate) <= max_base64_bytes and dims_ok:
                if scale_out is not None and image.size != original:
                    scale_out.update(orig_width=original[0], orig_height=original[1],
                                     new_width=image.width, new_height=image.height)
                return candidate
    if scale_out is not None and image.size != original:
        scale_out.update(orig_width=original[0], orig_height=original[1],
                         new_width=image.width, new_height=image.height)
    return candidate or raw()



