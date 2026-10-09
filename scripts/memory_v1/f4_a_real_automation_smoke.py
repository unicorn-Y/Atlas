"""Real Observer -> MemoryOS -> IntentBridge -> Automation F4-A smoke.

Uses one natural Chinese user message and the registered Observer model through
Atlas ModelRouter. All writable stores and the MemoryOS service are isolated.
Only sanitized evidence is retained in the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core"))
MODEL_CONFIG = Path(r"D:\Atlas\config\atlas.toml")
MODEL_SETTINGS = Path(r"D:\Atlas\data\user-settings.json")
PRODUCTION_ROOTS = (
    Path(r"D:\Atlas\data"),
    Path(r"D:\MemoryOSData"),
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "hermes",
)


class SmokeFailure(RuntimeError):
    def __init__(self, stage: str, code: str) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = code


def _assert_isolated(path: Path) -> None:
    resolved = path.resolve()
    for production in PRODUCTION_ROOTS:
        root = production.resolve()
        if resolved == root or root in resolved.parents:
            raise SmokeFailure("isolation", "PRODUCTION_PATH_REJECTED")


def _aware_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


async def _run() -> dict[str, Any]:
    from scripts.memory_v1.smoke_observer import _boot_isolated_memoryos

    temp_parent = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "Temp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    service = None
    capture = None
    client = None
    stage = "isolation"

    with tempfile.TemporaryDirectory(prefix="atlas-f4a-observer-", dir=temp_parent) as temp_name:
        root = Path(temp_name).resolve()
        _assert_isolated(root)
        atlas_root = root / "atlas-data"
        memoryos_root = root / "memoryos-data"
        memoryos_db = root / "memoryos-db" / "memoryos.sqlite3"
        hermes_root = root / "hermes-home"
        for path in (atlas_root, memoryos_root, memoryos_db.parent, hermes_root):
            path.mkdir(parents=True, exist_ok=True)
            _assert_isolated(path)

        os.environ.update({
            "ATLAS_DATA_DIR": str(atlas_root),
            "MEMORYOS_DATA_ROOT": str(memoryos_root),
            "MEMORYOS_DB_PATH": str(memoryos_db),
            "HERMES_HOME": str(hermes_root),
            "ATLAS_UNIFIED_EVENT_CLASS": "TEST",
        })

        try:
            stage = "isolated_memoryos_start"
            service = _boot_isolated_memoryos(memoryos_root, memoryos_db, atlas_root)

            stage = "safe_model_setup"
            from atlas.config import load_config
            from atlas.time_context import now_local, now_utc, timezone_name

            from scripts.memory_v1.gemini_runtime import (
                bootstrap_model_manager,
                clear_gateway_fallback_config,
                read_isolated_model_settings,
                write_isolated_user_settings,
            )

            config = load_config(MODEL_CONFIG)
            # The helper copies only allowlisted model/provider metadata and excludes
            # every credential value from the isolated settings file.
            settings = read_isolated_model_settings(MODEL_SETTINGS)
            settings_path = write_isolated_user_settings(atlas_root, settings)
            clear_gateway_fallback_config(config.raw)
            config.raw.setdefault("memory", {}).setdefault("unified", {}).update({
                "enabled": True,
                "service_url": f"http://127.0.0.1:{service.port}",
                "internal_token": service.token,
                "outbox_path": str(atlas_root / "outbox.db"),
            })
            manager, route = bootstrap_model_manager(config, settings, settings_path)
            model_id = str(route["observer_model_id"])
            zone_name = timezone_name(config)
            zone = ZoneInfo(zone_name)
            started_at = now_utc()
            local_now = now_local(config, now=started_at)
            requested_day = local_now.date() + timedelta(days=1)

            stage = "isolated_memory_pipeline_setup"
            from atlas.automation.engine import AutomationEngine
            from atlas.automation.store import AutomationStore
            from atlas.memory.capture import CaptureService
            from atlas.memory.intent_bridge import (
                IntentBridge,
                automation_id_for_intent,
                record_due_at,
                user_source_ref_from_record,
            )
            from atlas.memory.observer import MemoryObserver
            from atlas.memory.observer_drain import MemoryObserverDrain
            from atlas.memory.unified_client import UnifiedMemoryClient
            from atlas.memory.unified_facade import UnifiedMemoryFacade

            client = UnifiedMemoryClient(
                service_url=f"http://127.0.0.1:{service.port}",
                internal_token=service.token,
            )
            facade = UnifiedMemoryFacade(config=config, client=client)
            capture = CaptureService(
                facade=facade,
                config=config,
                outbox_path=atlas_root / "outbox.db",
                event_class="TEST",
            )
            outbox = capture._ensure_outbox()
            observer = MemoryObserver(manager, config, outbox=outbox)
            bridge = IntentBridge(facade=facade, config=config)
            store = AutomationStore(atlas_root / "automations.toml")
            engine = AutomationEngine(store)
            drain = MemoryObserverDrain(
                observer,
                facade,
                intent_bridge=bridge,
                automation_engine=engine,
            )

            stage = "capture_and_memoryos_source_ack"
            session_id = "f4a-" + uuid.uuid4().hex
            message_id = "user-" + uuid.uuid4().hex
            capture.capture_user_message(
                session_id,
                message_id,
                "明天上午9点提醒我交报告",
                occurred_at=local_now,
                source_timezone=zone_name,
            )
            await capture.flush()
            rows = outbox._conn.execute(
                "SELECT payload_json FROM outbox_events WHERE state = 'ACKED'",
            ).fetchall()
            sources: list[dict[str, Any]] = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                source = payload.get("observation", payload)
                locator = source.get("locator") or {}
                content = source.get("content") or {}
                if session_id in str(locator.get("value") or "") or content.get("session_id") == session_id:
                    if "text" not in source and isinstance(content, dict):
                        source["text"] = str(content.get("text") or "")
                    sources.append(source)
            if len(sources) != 1:
                raise SmokeFailure(stage, "USER_SOURCE_ACK_COUNT_MISMATCH")
            user_source_id = str(sources[0].get("source_event_id") or "")

            stage = "real_observer_model_extraction"
            batch = await observer.add_messages(
                session_id,
                sources,
                session_ended=True,
                context=facade.default_context(runtime_session_id=session_id),
            )
            if batch is None or not isinstance(batch.payload, dict):
                raise SmokeFailure(stage, "OBSERVER_RETURNED_NO_BATCH")
            observations = batch.payload.get("observations") or []
            intent_observations = [
                item for item in observations
                if isinstance(item, dict)
                and str((item.get("content") or {}).get("facet") or "").upper() == "INTENT"
            ]
            dated_observations = [
                item for item in observations
                if isinstance(item, dict)
                and _aware_datetime((item.get("content") or {}).get("valid_from")) is not None
            ]
            if not dated_observations:
                raise SmokeFailure(stage, "OBSERVER_RETURNED_NO_AWARE_VALID_FROM")
            observed_item = intent_observations[0] if intent_observations else dated_observations[0]
            observed_content = observed_item.get("content") or {}
            observed_facet = str(observed_content.get("facet") or "")
            observer_valid_from_raw = observed_content.get("valid_from")
            observer_valid_from = _aware_datetime(observer_valid_from_raw)
            if observer_valid_from is None:
                raise SmokeFailure(stage, "OBSERVER_VALID_FROM_NOT_AWARE")
            observer_local_due = observer_valid_from.astimezone(zone)

            stage = "memoryos_admission_and_intent_bridge"
            await drain.drain_once()
            listing = await facade.list_records(limit=100)
            records = listing.get("items") if isinstance(listing, dict) else None
            expected_source_ref = user_source_ref_from_record({
                "source_refs": [{"source_event_id": user_source_id}],
            })
            if not expected_source_ref:
                raise SmokeFailure(stage, "USER_SOURCE_REF_NOT_RESOLVABLE")
            candidate_records = [
                record for record in records or []
                if isinstance(record, dict)
                and user_source_ref_from_record(record) == expected_source_ref
            ]
            if not candidate_records:
                raise SmokeFailure(stage, "MEMORYOS_DERIVED_RECORD_NOT_FOUND")
            record = candidate_records[0]
            if not intent_observations:
                return {
                    "status": "FAILED",
                    "failure_stage": "real_observer_model_extraction",
                    "failure_code": "OBSERVER_DID_NOT_EXTRACT_INTENT",
                    "pipeline": "Atlas Capture -> Observer/ModelRouter -> MemoryOS HTTP -> IntentBridge -> AutomationStore",
                    "model_id": model_id,
                    "model_provider_id": str(route.get("provider_id") or ""),
                    "provider_endpoint_host": str(route.get("provider_endpoint_host") or ""),
                    "credential_value_recorded": False,
                    "timezone": zone_name,
                    "local_now": local_now.isoformat(),
                    "user_source_event_id": user_source_id,
                    "observer_input_tokens": int(batch.input_tokens),
                    "observer_output_tokens": int(batch.output_tokens),
                    "observer_facet": observed_facet,
                    "observer_valid_from": str(observer_valid_from_raw),
                    "observer_valid_from_local": observer_local_due.isoformat(),
                    "memory_record_ref": str(record.get("record_ref") or ""),
                    "memory_record_facet": str(record.get("facet") or ""),
                    "memoryos_derived_record_admitted": True,
                    "unified_intent_created": False,
                    "automation_created": False,
                    "source_store_isolated": True,
                    "memoryos_store_isolated": True,
                    "chat_session_created": False,
                }
            intent_due = record_due_at(record)
            if not intent_due:
                raise SmokeFailure(stage, "MEMORYOS_INTENT_HAS_NO_AWARE_DUE_AT")
            intent_row = await bridge.find_intent_for_record(record)
            if not isinstance(intent_row, dict) or not intent_row.get("intent_id"):
                raise SmokeFailure(stage, "UNIFIED_INTENT_NOT_FOUND")

            stage = "automation_store_write"
            automation_id = automation_id_for_intent(str(intent_row["intent_id"]))
            stored = store.get(automation_id)
            if not isinstance(stored, dict):
                raise SmokeFailure(stage, "AUTOMATION_NOT_STORED")
            trigger = stored.get("trigger") or {}
            trigger_at = str(trigger.get("at") or "")
            trigger_dt = _aware_datetime(trigger_at)
            if trigger_dt is None:
                raise SmokeFailure(stage, "AUTOMATION_TRIGGER_NOT_AWARE")
            trigger_local = trigger_dt.astimezone(zone)

            valid_from_matches = (
                observer_local_due.date() == requested_day
                and observer_local_due.hour == 9
                and observer_local_due.minute == 0
                and observer_valid_from.utcoffset() == observer_local_due.utcoffset()
            )
            trigger_matches = (
                trigger_local.date() == requested_day
                and trigger_local.hour == 9
                and trigger_local.minute == 0
            )
            intent_dt = _aware_datetime(intent_due)
            if not valid_from_matches:
                raise SmokeFailure("real_observer_model_extraction", "VALID_FROM_NOT_LOCAL_TOMORROW_0900")
            if intent_dt is None or intent_dt.astimezone(zone) != trigger_local:
                raise SmokeFailure("automation_store_write", "INTENT_AUTOMATION_TIME_MISMATCH")
            if not trigger_matches:
                raise SmokeFailure("automation_store_write", "TRIGGER_NOT_LOCAL_TOMORROW_0900")

            return {
                "status": "COMPLETED",
                "pipeline": "Atlas Capture -> Observer/ModelRouter -> MemoryOS HTTP -> IntentBridge -> AutomationStore",
                "model_id": model_id,
                "model_provider_id": str(route.get("provider_id") or ""),
                "provider_endpoint_host": str(route.get("provider_endpoint_host") or ""),
                "credential_value_recorded": False,
                "timezone": zone_name,
                "local_now": local_now.isoformat(),
                "user_source_event_id": user_source_id,
                "observer_input_tokens": int(batch.input_tokens),
                "observer_output_tokens": int(batch.output_tokens),
                "observer_intent_count": len(intent_observations),
                "observer_facet": observed_facet,
                "observer_valid_from": str(observer_valid_from_raw),
                "observer_valid_from_local": observer_local_due.isoformat(),
                "memory_record_ref": str(record.get("record_ref") or ""),
                "unified_intent_id": str(intent_row["intent_id"]),
                "intent_due_at": intent_due,
                "automation_id": automation_id,
                "automation_trigger_at": trigger_at,
                "automation_trigger_local": trigger_local.isoformat(),
                "expected_local_date": requested_day.isoformat(),
                "source_store_isolated": True,
                "memoryos_store_isolated": True,
                "chat_session_created": False,
            }
        except SmokeFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - retain only a safe stage and error type
            raise SmokeFailure(stage, type(exc).__name__) from None
        finally:
            if capture is not None:
                capture.close()
            if client is not None:
                await client.aclose()
            if service is not None:
                service.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs/plan/MEMORY-V1/progress/f4_a_automation_smoke.json",
    )
    args = parser.parse_args()
    artifact = args.output.resolve()
    if REPO_ROOT not in artifact.parents:
        raise SystemExit("smoke evidence must be written inside the Atlas repository")

    try:
        result = asyncio.run(_run())
    except SmokeFailure as exc:
        safe = {"status": "FAILED", "stage": exc.stage, "failure_code": exc.code}
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"F4-A real observer pipeline smoke failed at {exc.stage}; evidence: {artifact}")
        return 1
    except Exception as exc:  # noqa: BLE001 - do not print provider or config errors
        safe = {
            "status": "FAILED",
            "stage": "startup",
            "failure_type": type(exc).__name__,
            "failure_code": "UNCLASSIFIED",
        }
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"F4-A real observer pipeline smoke failed ({type(exc).__name__}); evidence: {artifact}")
        return 1

    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.get("status") != "COMPLETED":
        print(
            f"F4-A real observer pipeline smoke failed at {result['failure_stage']}; "
            f"evidence: {artifact}"
        )
        return 1
    print(
        f"F4-A real observer pipeline smoke {result['status']}: "
        f"{result['model_id']} -> {result['automation_trigger_local']} {result['timezone']}; "
        f"evidence: {artifact}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
