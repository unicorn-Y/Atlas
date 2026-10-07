"""Real ModelRouter smoke for S4 Reflector.

Invokes the real ModelRouter (deepseek-v4.1-flash via gateway) to propose consolidation
operations (MERGE, SUPERSEDE, ROLLUP_DAY, PROFILE_UPDATE, IMPORTANCE) on memory records.
Guarantees strict data isolation: writes only to ATLAS_DATA_DIR.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

PRODUCTION_ROOTS = (
    Path(r"D:\Atlas\data"),
    Path(r"D:\MemoryOSData"),
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "hermes",
)


def _isolated_roots() -> tuple[Path, Path, Path, Path]:
    names = ("ATLAS_DATA_DIR", "MEMORYOS_DATA_ROOT", "MEMORYOS_DB_PATH", "HERMES_HOME")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("isolated smoke roots are required: " + ", ".join(missing))
    roots = tuple(Path(os.environ[name]).resolve() for name in names)
    for path in roots:
        for production in PRODUCTION_ROOTS:
            production = production.resolve()
            if path == production or production in path.parents:
                raise RuntimeError(f"refusing production data path: {path}")
    return roots  # type: ignore[return-value]


def _load_readonly_model_config() -> dict[str, Any]:
    config_path = Path(
        os.environ.get("ATLAS_MEMORY_V1_MODEL_CONFIG_READONLY", r"D:\Atlas\config\atlas.toml")
    ).resolve()
    from atlas import config as atlas_config
    from atlas.config import AtlasConfig

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    config = AtlasConfig(raw)
    atlas_config.get_config = lambda: config

    from atlas.models import manager as model_manager_module

    model_manager_module.get_config = lambda: config
    return raw


def _build_sample_trace_records() -> list[dict[str, Any]]:
    """Build candidate records reflecting 2-week trace milestones for real smoke."""
    return [
        {
            "record_ref": "memory:rec-001",
            "facet": "FACT",
            "recorded_at": "2026-09-24T09:30:00Z",
            "valid_time": {"valid_from": "2026-09-24"},
            "content": {"text": "用户刚来杭州余杭工作，在做跨境电商相关业务。"},
        },
        {
            "record_ref": "memory:rec-002",
            "facet": "FACT",
            "recorded_at": "2026-09-24T09:35:00Z",
            "valid_time": {"valid_from": "2026-09-24"},
            "content": {"text": "用户在杭州从事跨境电商。"},
        },
        {
            "record_ref": "memory:rec-003",
            "facet": "PREFERENCE",
            "recorded_at": "2026-09-24T09:40:00Z",
            "valid_time": {"valid_from": "2026-09-24"},
            "content": {"text": "用户对花生严重过敏，外出就餐需格外注意。"},
        },
        {
            "record_ref": "memory:rec-004",
            "facet": "STATE",
            "recorded_at": "2026-09-24T10:00:00Z",
            "valid_time": {"valid_from": "2026-09-24"},
            "content": {"text": "开发设备：目前使用一台 Windows 笔记本。"},
        },
        {
            "record_ref": "memory:rec-005",
            "facet": "STATE",
            "recorded_at": "2026-10-02T15:00:00Z",
            "valid_time": {"valid_from": "2026-10-02"},
            "content": {"text": "开发设备变更：用户新换了一台 MacBook Pro，Windows 笔记本已作为备用。"},
        },
        {
            "record_ref": "memory:rec-006",
            "facet": "EPISODE",
            "recorded_at": "2026-10-05T14:00:00Z",
            "valid_time": {"valid_from": "2026-10-05"},
            "content": {"text": "10月5日与海外供应商完成了秋季选品线上会议，确认了首批测试订单。"},
        },
    ]


async def _run(output_file: Path | None = None) -> int:
    atlas_root, _, _, _ = _isolated_roots()
    _load_readonly_model_config()

    from atlas.memory.reflector import MemoryReflector
    from atlas.models import ModelManager

    manager = ModelManager()
    reflector = MemoryReflector(manager)

    records = _build_sample_trace_records()
    print(f"Loaded {len(records)} candidate memories for reflection.")

    t0 = time.perf_counter()
    result = await reflector.reflect(
        "test-smoke-subject",
        records,
        force=True,  # test full reflection pipeline
    )
    duration = time.perf_counter() - t0

    artifact_data = {
        "status": "COMPLETED",
        "reflected": result.reflected,
        "model_id": result.model_id,
        "duration_seconds": round(duration, 3),
        "token_usage": result.token_usage,
        "locally_accepted": result.locally_accepted,
        "locally_rejected": result.locally_rejected,
    }

    out_path = output_file or (atlas_root / "reflector-smoke-result.json")
    out_path.write_text(json.dumps(artifact_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Reflector Real Model Smoke Results ===")
    print(f"Status: {artifact_data['status']}")
    print(f"Model ID: {result.model_id}")
    print(f"Duration: {artifact_data['duration_seconds']}s")
    print(f"Token Usage: {artifact_data['token_usage']}")
    print(f"Accepted Operations: {len(result.locally_accepted)}")
    for op in result.locally_accepted:
        print(f"  - [{op['op']}]: {op}")
    print(f"Rejected Operations: {len(result.locally_rejected)}")
    for op in result.locally_rejected:
        print(f"  - [{op.get('op')}]: {op.get('reason')}")
    print(f"Artifact written to: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Custom output JSON path")
    args = parser.parse_args()
    return asyncio.run(_run(args.output))


if __name__ == "__main__":
    sys.exit(main())
