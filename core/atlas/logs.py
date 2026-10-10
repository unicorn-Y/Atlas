"""Backend logging and compact per-run diagnostic events."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from atlas.config import DATA_ROOT, AtlasConfig, get_config

LOG_DIR = DATA_ROOT / "data" / "logs"
_configure_lock = threading.Lock()
_event_lock = threading.Lock()
_run_paths: dict[str, Path] = {}
_SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token",
                   "access_token", "refresh_token", "credentials"}
_SECRET_TEXT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


def configure_logging(config: AtlasConfig | None = None) -> Path:
    """Install Atlas handlers once; JSON on disk, configured format on stderr."""
    config = config or get_config()
    level = getattr(logging, config.log_level, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "backend.log"
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    with _configure_lock:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_atlas_runtime_handler", False):
                root.removeHandler(handler)
                handler.close()
        file_handler = TimedRotatingFileHandler(
            log_path, when="midnight", backupCount=14, encoding="utf-8", utc=True,
        )
        console_handler = logging.StreamHandler(sys.stderr)
        renderers = (
            structlog.processors.JSONRenderer(ensure_ascii=False),
            structlog.processors.JSONRenderer(ensure_ascii=False)
            if config.log_format.lower() == "json"
            else structlog.dev.ConsoleRenderer(colors=False),
        )
        for handler, renderer in zip((file_handler, console_handler), renderers):
            handler._atlas_runtime_handler = True  # type: ignore[attr-defined]
            handler.setLevel(level)
            handler.setFormatter(structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=processors,
                processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
            ))
            root.addHandler(handler)
        root.setLevel(level)
        structlog.configure(
            processors=[structlog.stdlib.filter_by_level, *processors,
                        structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )
        access_log = logging.getLogger("uvicorn.access")
        access_log.setLevel(logging.WARNING)
    return log_path


def _summary(value: Any, key: str = "") -> Any:
    normalized = key.lower().replace("-", "_")
    if normalized in _SENSITIVE_KEYS or normalized.endswith(("_api_key", "_secret", "_password")):
        return "[redacted]"
    if normalized in {"output", "stdout", "stderr", "content", "prompt", "arguments"}:
        return {"length": len(value) if isinstance(value, (str, bytes, list, dict)) else 0}
    if isinstance(value, dict):
        return {str(k): _summary(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_summary(item) for item in value[:20]]
    if isinstance(value, str):
        value = _SECRET_TEXT.sub(r"\1\2[redacted]", value)
        value = _BEARER_TEXT.sub("Bearer [redacted]", value)
        return value[:1000] + ("…" if len(value) > 1000 else "")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _summary(str(value))


def append_run_event(run_id: str, event: str, **fields: Any) -> Path:
    """Append one event and return its file path; fields are metadata/summaries only.

    The first event fixes the run's date directory, including runs crossing midnight.
    Full output/prompt/arguments fields become lengths; secret fields are redacted.
    Callers must avoid embedding credentials in free-form summaries.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
        raise ValueError("run_id must contain only letters, digits, underscores or hyphens")
    now = datetime.now(timezone.utc)
    record = {
        **_summary(fields),
        "timestamp": now.isoformat(),
        "event": event,
        "run_id": run_id,
    }
    with _event_lock:
        event_path = _run_paths.setdefault(run_id, LOG_DIR / "runs" / now.strftime("%Y-%m-%d") / f"{run_id}.jsonl")
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        if event == "run_end":
            _run_paths.pop(run_id, None)
    return event_path
