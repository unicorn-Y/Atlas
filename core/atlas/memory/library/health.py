"""Read-only health probes for the memory library.

The diagnostics page has to answer "is anything stuck?" without touching the
library, so every probe here only reads files and opens the queue database with
``mode=ro``. Each probe isolates its own failure: a corrupt database or a
missing checkpoint file must never stop the page from loading, and
:func:`memory_health` never raises.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

QUEUE_FILENAME = ".queue.sqlite"
DREAM_STATE_FILENAME = ".dream-state.json"
#: A pending turn older than this means the drain loop is not making progress.
STUCK_PENDING_SECONDS = 60 * 60
#: A checkpoint older than this means consolidation stopped running.
DREAM_LAG_LIMIT_SECONDS = 3 * 24 * 60 * 60
_READONLY_TIMEOUT = 5.0


def memory_root() -> Path:
    """Memory-library root, resolved exactly like ``get_library()`` but read-only."""
    from atlas.config import DATA_ROOT, get_config

    try:
        configured = str(get_config().get("memory.library.root", "") or "").strip()
    except Exception:  # noqa: BLE001 - a broken config must not hide the data root
        configured = ""
    chosen = os.environ.get("ATLAS_TEST_MEMORY_ROOT", "").strip() or configured
    return Path(chosen) if chosen else Path(DATA_ROOT) / "data" / "memory"


def memory_enabled() -> bool:
    from atlas.config import get_config

    try:
        return bool(get_config().get("memory.library.enabled", True))
    except Exception:  # noqa: BLE001
        return True


def queue_path(root: Path | None = None) -> Path:
    return Path(root or memory_root()) / QUEUE_FILENAME


def dream_state_path(root: Path | None = None) -> Path:
    return Path(root or memory_root()) / DREAM_STATE_FILENAME


def readonly_connection(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only; the file must already exist."""
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=_READONLY_TIMEOUT)
    db.row_factory = sqlite3.Row
    return db


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment


def _age_seconds(moment: datetime | None, now: datetime) -> float | None:
    if moment is None:
        return None
    return round(max(0.0, (now - moment.astimezone(UTC)).total_seconds()), 1)


def _due(row: dict[str, Any], now: datetime) -> bool:
    """True when the queue would pick this row up now (NULL backoff means due)."""
    raw = row.get("next_attempt_at")
    if raw is None or str(raw).strip() == "":
        return True
    moment = _parse_iso(raw)
    return moment is None or moment <= now


def _queue_probe(root: Path, now: datetime) -> dict[str, Any]:
    path = queue_path(root)
    result: dict[str, Any] = {
        "queue_path": str(path),
        "queue_exists": path.exists(),
        "queue_total": 0,
        "queue_pending": 0,
        "queue_exhausted": 0,
        "oldest_pending_at": None,
        "oldest_pending_age_seconds": None,
        "last_error": None,
        "last_error_at": None,
        "last_success_at": None,
    }
    if not path.exists():
        return result
    try:
        db = readonly_connection(path)
    except sqlite3.Error as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    try:
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(pending)")}
        if not columns:
            result["error"] = "pending table is missing"
            return result
        rows = [dict(row) for row in db.execute("SELECT * FROM pending ORDER BY id")]
        total = pending = exhausted = 0
        oldest: datetime | None = None
        oldest_text = ""
        newest_error: tuple[float, str, str] | None = None
        for row in rows:
            total += 1
            try:
                attempts = int(row.get("attempts") or 0)
            except (TypeError, ValueError):
                attempts = 0
            if attempts > 0:
                exhausted += 1
            if _due(row, now):
                pending += 1
            created = _parse_iso(row.get("created"))
            if created is not None and (oldest is None or created < oldest):
                oldest = created
                oldest_text = str(row.get("created"))
            message = str(row.get("last_error") or "").strip()
            if message:
                at_text = str(row.get("last_error_at") or row.get("created") or "")
                stamp = _parse_iso(at_text)
                key = stamp.timestamp() if stamp is not None else float("-inf")
                if newest_error is None or key >= newest_error[0]:
                    newest_error = (key, message, at_text)
        result.update({
            "queue_total": total,
            "queue_pending": pending,
            "queue_exhausted": exhausted,
            "oldest_pending_at": oldest_text or None,
            "oldest_pending_age_seconds": _age_seconds(oldest, now),
        })
        if newest_error is not None:
            result["last_error"] = newest_error[1]
            result["last_error_at"] = newest_error[2] or None
        try:
            meta = {
                str(row["key"]): str(row["value"])
                for row in db.execute("SELECT key, value FROM meta")
            }
        except sqlite3.Error:
            meta = {}
        result["last_success_at"] = meta.get("last_success_at") or None
        return result
    except sqlite3.Error as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        db.close()


def _dream_probe(root: Path, now: datetime) -> dict[str, Any]:
    path = dream_state_path(root)
    result: dict[str, Any] = {
        "dream_state_path": str(path),
        "dream_checkpoint": None,
        "dream_lag_seconds": None,
    }
    if not path.exists():
        return result
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if not isinstance(state, dict):
        result["error"] = "dream state is not a JSON object"
        return result
    checkpoint = str(state.get("checkpoint") or "").strip()
    result["dream_checkpoint"] = checkpoint or None
    moment = _parse_iso(checkpoint)
    if moment is None:
        if checkpoint:
            result["error"] = "dream checkpoint is not a parseable timestamp"
        return result
    result["dream_lag_seconds"] = _age_seconds(moment, now)
    return result


def memory_health() -> dict[str, Any]:
    """Snapshot of memory-library queue and consolidation health.

    Read-only, never raises: any failure is reported as ``ok: False`` plus an
    ``error``/``problems`` entry instead of an exception.
    """
    now = datetime.now(UTC)
    result: dict[str, Any] = {
        "ok": True,
        "generated_at": now.isoformat(timespec="seconds"),
        "root": "",
        "enabled": True,
        "queue_path": "",
        "queue_exists": False,
        "queue_pending": 0,
        "queue_exhausted": 0,
        "queue_total": 0,
        "oldest_pending_at": None,
        "oldest_pending_age_seconds": None,
        "last_error": None,
        "last_error_at": None,
        "last_success_at": None,
        "dream_state_path": "",
        "dream_checkpoint": None,
        "dream_lag_seconds": None,
        "problems": [],
    }
    try:
        root = memory_root()
        result["root"] = str(root)
        result["enabled"] = memory_enabled()
    except Exception as exc:  # noqa: BLE001 - health must always answer
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    probes = (("queue", _queue_probe), ("dream", _dream_probe))
    for name, probe in probes:
        try:
            part = probe(root, now)
        except Exception as exc:  # noqa: BLE001 - one broken probe must not hide the other
            result["problems"].append({"probe": name, "error": f"{type(exc).__name__}: {exc}"})
            result["ok"] = False
            continue
        error = part.pop("error", None)
        result.update({key: value for key, value in part.items() if key != "error"})
        if error:
            result["problems"].append({"probe": name, "error": str(error)})
            result["ok"] = False

    try:
        if int(result.get("queue_exhausted") or 0) > 0:
            result["problems"].append({
                "probe": "queue",
                "error": f"{result['queue_exhausted']} 条记忆待办正在退避重试",
            })
            result["ok"] = False
        oldest = result.get("oldest_pending_age_seconds")
        if oldest is not None and float(oldest) > STUCK_PENDING_SECONDS:
            result["problems"].append({
                "probe": "queue",
                "error": f"最旧的待办已积压 {int(float(oldest))} 秒",
            })
            result["ok"] = False
        lag = result.get("dream_lag_seconds")
        if lag is not None and float(lag) > DREAM_LAG_LIMIT_SECONDS:
            result["problems"].append({
                "probe": "dream",
                "error": f"整理检查点已落后 {int(float(lag))} 秒",
            })
            result["ok"] = False
    except Exception as exc:  # noqa: BLE001 - thresholds must not raise either
        result["problems"].append({"probe": "summary", "error": f"{type(exc).__name__}: {exc}"})
        result["ok"] = False
    return result


__all__ = [
    "QUEUE_FILENAME",
    "DREAM_STATE_FILENAME",
    "STUCK_PENDING_SECONDS",
    "DREAM_LAG_LIMIT_SECONDS",
    "memory_root",
    "memory_enabled",
    "queue_path",
    "dream_state_path",
    "readonly_connection",
    "memory_health",
]
