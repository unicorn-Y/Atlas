"""Isolated, read-only adapter call for one skill-market source."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from atlas.skills.market import (
    SEARCH_WORKER_MAX_INPUT_BYTES,
    SEARCH_WORKER_MAX_OUTPUT_BYTES,
    MarketError,
    SkillMarket,
)

logger = logging.getLogger(__name__)


def _search(payload: dict[str, Any]) -> dict[str, Any]:
    required_paths = ("data_dir", "user_skills_dir", "source")
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_paths):
        raise MarketError("技能市场搜索配置无效。", code="invalid_search")
    query = payload.get("query", "")
    source = payload["source"]
    limit = payload.get("limit", 20)
    if not isinstance(query, str) or not isinstance(limit, int):
        raise MarketError("技能市场搜索请求无效。", code="invalid_search")

    project_skills = payload.get("project_skills_dir")
    hermes_root = payload.get("hermes_root")
    hub_state_dir = payload.get("hub_state_dir")
    market = SkillMarket(
        registry=None,
        data_dir=Path(payload["data_dir"]),
        user_skills_dir=Path(payload["user_skills_dir"]),
        project_skills_dir=Path(project_skills) if project_skills else None,
        hermes_root=Path(hermes_root) if hermes_root else None,
        hub_state_dir=Path(hub_state_dir) if hub_state_dir else None,
    )
    adapter = market._adapter_for(source)
    with market._proxy_env(adapter.source_id()):
        items = list(adapter.search(query, limit=max(1, min(limit, 100))) or [])

    results: list[dict[str, Any]] = []
    for item in items:
        data = item if isinstance(item, dict) else vars(item)
        extra = data.get("extra") or {}
        results.append({
            "source": data.get("source") or adapter.source_id(),
            "identifier": data.get("identifier") or "",
            "name": data.get("name") or "",
            "description": data.get("description") or "",
            "trust_level": data.get("trust_level") or "community",
            "tags": list(data.get("tags") or []),
            "extra": extra if isinstance(extra, dict) else {},
        })
    return {"results": results}


def run_stdio() -> None:
    """Read one bounded JSON request and write one bounded JSON response."""
    raw = sys.stdin.buffer.read(SEARCH_WORKER_MAX_INPUT_BYTES + 1)
    if len(raw) > SEARCH_WORKER_MAX_INPUT_BYTES or sys.stdin.buffer.read(1):
        response: dict[str, Any] = {
            "error": {"code": "invalid_search", "message": "技能市场搜索请求过大。"},
        }
    else:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise MarketError("技能市场搜索请求无效。", code="invalid_search")
            with redirect_stdout(sys.stderr):
                response = _search(payload)
        except MarketError as exc:
            response = {"error": {"code": exc.code, "message": exc.message}}
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = {
                "error": {"code": "invalid_search", "message": "技能市场搜索请求无效。"},
            }
        except Exception:
            # Any source failure becomes a structured reply; the traceback goes to stderr.
            logger.exception("market search worker: source failed")
            response = {
                "error": {"code": "source_unavailable", "message": "技能市场来源暂时不可用。"},
            }

    encoded = json.dumps(
        response, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > SEARCH_WORKER_MAX_OUTPUT_BYTES:
        encoded = json.dumps(
            {"error": {
                "code": "response_too_large", "message": "技能市场来源返回内容过大。",
            }}, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()

