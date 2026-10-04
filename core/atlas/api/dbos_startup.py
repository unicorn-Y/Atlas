"""S5 (H8 §10.2): DBOS system-database migrations only on a version change.

Every cold start used to re-apply the full DBOS SQLite migration ladder. The
backend now records ``{atlas_version, dbos_version}`` next to the system
database after a successful start; when both match the running versions and
the system database file exists, the launcher is told to verify instead of
migrate (``run_migrations=False`` — DBOS then asserts the applied schema
version without writing). A missing record or any version change runs
migrations exactly as before and refreshes the record.

First-run behavior is unchanged: no record → migrate.
"""

from __future__ import annotations

import json
import time
from importlib import metadata
from pathlib import Path
from typing import Any

import structlog

from atlas import __version__ as ATLAS_VERSION

log = structlog.get_logger(__name__)

_META_FILENAME = "dbos-startup.json"


def _meta_path(data_dir: Path) -> Path:
    return data_dir / _META_FILENAME


def _dbos_version() -> str:
    try:
        return metadata.version("dbos")
    except metadata.PackageNotFoundError:
        return "unknown"


def migrations_current(data_dir: Path) -> bool:
    """True when the recorded versions match and the system DB exists."""
    path = _meta_path(data_dir)
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    current = record.get("atlas_version") == ATLAS_VERSION and (
        record.get("dbos_version") == _dbos_version()
    )
    if current and not (data_dir / "dbos.sqlite").is_file():
        return False
    return current


def record_started(data_dir: Path, *, started: bool) -> None:
    """Persist the version record after a successful backend start."""
    if not started:
        return
    payload = {
        "atlas_version": ATLAS_VERSION,
        "dbos_version": _dbos_version(),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        _meta_path(data_dir).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8",
        )
    except OSError:
        # The record is a warm-start optimization only; a write failure must
        # never fail startup — the next run just migrates again.
        log.warning("dbos.startup_record_write_failed", path=str(_meta_path(data_dir)))
