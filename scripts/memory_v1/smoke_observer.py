"""Real ModelRouter and MemoryOS HTTP smoke test for S2 Observer.

Exercises:
  1. Real model deepseek-v4.1-flash via gateway for structured memory observation.
  2. Isolated MemoryOS HTTP service on temporary data root.
  3. Real capture ACK gate -> Observer extraction -> Drain POST -> MemoryOS admission.
  4. 10 Chinese dialogue cases matching 00_任务书.md S2:
     - Case 1: 陈述与提问混在一起 (Mixed statement and question)
     - Case 2: 偏好 (User preference)
     - Case 3: 项目约束 (Project constraint)
     - Case 4: 状态变化（"本来周三，改周五"） (State change)
     - Case 5: 提到两个同名的人 (Two people with the same name)
     - Case 6: 粘贴一段网页内容 (Web content / third-party article)
     - Case 7: 经历/日常事件（无 key 记忆） (Episode / keyless event)
     - Case 8: 习惯 (Habit)
     - Case 9: 承诺/行动承诺 (Commitment)
     - Case 10: 关系/人际 (Relation)
  5. GET /v1/unified/evidence/{ref} validation for all formed records.
  6. Acceptance criteria validation:
     - 用户陈述被正确形成 >= 9 条
     - 提问或网页内容被误当成用户事实 = 0
     - 每条记忆均能通过 GET /v1/unified/evidence/{ref} 打开原句
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import uuid
from dataclasses import dataclass
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

SMOKE_CASES: list[dict[str, Any]] = [
    {
        "id": "case_01_mixed_statement_and_question",
        "title": "陈述与提问混在一起",
        "user_message": "我下周三要飞去深圳参加开源操作系统峰会。对了，你觉得深圳那几天的天气会下雨吗？",
        "assistant_reply": "好的，已为您记录行程。深圳近期天气多云，建议出行前查看最新天气预报。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "陈述（去深圳参加峰会）形成记忆；提问（深圳天气是否下雨）不得成为用户事实。",
    },
    {
        "id": "case_02_preference",
        "title": "偏好",
        "user_message": "我平时写代码最喜欢用 Python，但写前端坚决不用 Vue，只用 React。",
        "assistant_reply": "明白了，前端技术栈锁定为 React，后端采用 Python。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "技术偏好（后端偏好Python，前端只用React不用Vue）。",
    },
    {
        "id": "case_03_project_constraint",
        "title": "项目约束",
        "user_message": "Atlas 项目所有对外部大模型的调用必须通过 ModelRouter 进行路由，严禁各模块私自直连模型网关。",
        "assistant_reply": "收到，严格遵守该架构约束，全部模型调用统一接入 ModelRouter。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "项目约束（大模型调用必须走ModelRouter，严禁私自直连网关）。",
    },
    {
        "id": "case_04_state_change",
        "title": "状态变化（本来周三，改周五）",
        "user_message": "关于周报评审会的时间，本来定在周三上午十点，现在改到了周五下午三点。",
        "assistant_reply": "已更新会议时间：周报评审会调整至周五下午三点举行。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "状态变更（周报评审会改到周五下午三点，原定周三）。",
    },
    {
        "id": "case_05_same_name_entities",
        "title": "提到两个同名的人",
        "user_message": "我们研发部有两个李明，做前端的李明来自成都，做大模型算法的李明来自武汉。算法李明上周刚发了一篇新论文。",
        "assistant_reply": "已记录两位李明的信息：前端李明（成都）与算法李明（武汉，上周发表新论文）。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "同名人物区分（前端李明/成都 vs 算法李明/武汉/发表论文）。",
    },
    {
        "id": "case_06_web_content_third_party",
        "title": "粘贴一段网页内容（不得成为用户事实）",
        "user_message": "给你看一篇网页新闻：【科技快讯：根据TechDaily报道，某知名AI公司今日宣布将在西雅图裁员30%，全面转向自动编程工具。】",
        "assistant_reply": "已阅读该新闻，这是关于某AI公司西雅图裁员和转型的第三方媒体报道。",
        "is_external": True,
        "expect_user_statements": 0,
        "description": "网页新闻内容系第三方材料，speaker不得为USER，不得成为用户事实。",
    },
    {
        "id": "case_07_keyless_episode",
        "title": "经历/日常事件（无 key 记忆）",
        "user_message": "上个周末我和大学室友一起去奥林匹克森林公园徒步了十公里，路上还拍到了黑天鹅。",
        "assistant_reply": "听起来是很惬意的周末徒步经历！",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "无 key 经历事件（奥森公园徒步十公里并拍到黑天鹅）。",
    },
    {
        "id": "case_08_habit",
        "title": "习惯",
        "user_message": "我习惯每天早上八点半准时晨跑五公里，已经坚持了三年。",
        "assistant_reply": "很有毅力的习惯！每天早晨 8:30 晨跑 5 公里已记录。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "日常习惯（每天8:30晨跑5公里）。",
    },
    {
        "id": "case_09_commitment",
        "title": "承诺/行动承诺",
        "user_message": "我已经答应导师在这个月月底前把分布式存储系统的基准测试完整报告提交上去。",
        "assistant_reply": "收到承诺事项：本月底前完成并提交分布式存储系统基准测试报告。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "行动承诺（月底前提交基准测试报告）。",
    },
    {
        "id": "case_10_relation",
        "title": "关系/人际",
        "user_message": "王教授是我的博士生导师，我们在多模态大模型对齐方向上已经合作研究了两年。",
        "assistant_reply": "已记录：王教授为您的博士导师，合作方向为多模态大模型对齐。",
        "is_external": False,
        "expect_user_statements": 1,
        "description": "师生合作关系（王教授为博士导师，合作多模态大模型对齐研究）。",
    },
]


def _ensure_isolated_roots() -> tuple[Path, Path, Path, Path]:
    names = ("ATLAS_DATA_DIR", "MEMORYOS_DATA_ROOT", "MEMORYOS_DB_PATH", "HERMES_HOME")
    if not all(os.environ.get(name) for name in names):
        temp_dir = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "Temp"
        run_id = "atlas_smoke_s2_" + uuid.uuid4().hex[:8]
        iso_root = temp_dir / run_id
        atlas_data = iso_root / "atlas_data"
        mos_data = iso_root / "mos_data"
        mos_db = iso_root / "mos_db" / "memoryos.sqlite3"
        hermes_home = iso_root / "hermes_home"
        atlas_data.mkdir(parents=True, exist_ok=True)
        mos_data.mkdir(parents=True, exist_ok=True)
        mos_db.parent.mkdir(parents=True, exist_ok=True)
        hermes_home.mkdir(parents=True, exist_ok=True)

        # Prepare isolated config files
        prod_atlas_toml = Path(r"D:\Atlas\config\atlas.toml")
        if prod_atlas_toml.exists():
            (atlas_data / "config").mkdir(parents=True, exist_ok=True)
            (atlas_data / "config" / "atlas.toml").write_text(
                prod_atlas_toml.read_text(encoding="utf-8"), encoding="utf-8"
            )
        (atlas_data / "user-settings.json").write_text(
            json.dumps({"memory_model": "deepseek-v4.1-flash", "default_model": "deepseek-v4.1-flash"}),
            encoding="utf-8",
        )
        (hermes_home / "config.yaml").write_text("{}", encoding="utf-8")

        os.environ["ATLAS_DATA_DIR"] = str(atlas_data)
        os.environ["MEMORYOS_DATA_ROOT"] = str(mos_data)
        os.environ["MEMORYOS_DB_PATH"] = str(mos_db)
        os.environ["HERMES_HOME"] = str(hermes_home)

    roots = tuple(Path(os.environ[name]).resolve() for name in names)
    for path in roots:
        for production in PRODUCTION_ROOTS:
            production = production.resolve()
            if path == production or production in path.parents:
                raise RuntimeError(f"refusing production data path: {path}")
    return roots  # type: ignore[return-value]


def _find_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _apply_model_config() -> tuple[dict[str, Any], Any]:
    from atlas import config as atlas_config
    from atlas.config import AtlasConfig
    import atlas.models.manager as model_manager_module

    config_path = Path(os.environ.get(
        "ATLAS_MEMORY_V1_MODEL_CONFIG_READONLY", r"D:\Atlas\config\atlas.toml",
    )).resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    config = AtlasConfig(raw)

    atlas_config.get_config = lambda: config
    model_manager_module.get_config = lambda: config
    atlas_config.load_user_settings = lambda path=None: {
        "memory_model": "deepseek-v4.1-flash",
        "default_model": "deepseek-v4.1-flash",
    }
    return raw, config


@dataclass
class ServiceInstance:
    process: subprocess.Popen
    port: int
    token: str
    log_file: Path

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _boot_isolated_memoryos(
    mos_root: Path, mos_db: Path, atlas_root: Path,
) -> ServiceInstance:
    port = _find_free_port()
    token = "smoke-token-" + uuid.uuid4().hex[:12]
    service_dir = Path(r"D:\MemoryOS\service")
    py = service_dir / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)

    log_file = mos_root / "memoryos_service.log"
    fh = open(log_file, "wb")

    env = dict(os.environ)
    env.update({
        "MEMORYOS_DATA_ROOT": str(mos_root),
        "MEMORYOS_DB_PATH": str(mos_db),
        "ATLAS_DATA_DIR": str(atlas_root),
        "MEMORYOS_INTERNAL_TOKEN": token,
        "MEMORYOS_OWNER_TOKEN": "smoke-owner",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "MEMORYOS_FORMATION_WORKER": "0",
    })

    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(service_dir),
        env=env,
        stdout=fh,
        stderr=subprocess.STDOUT,
    )

    started = False
    for _ in range(60):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    started = True
                    break
        except Exception:
            pass
        if proc.poll() is not None:
            break
        time.sleep(0.2)

    if not started:
        proc.kill()
        fh.close()
        raise RuntimeError(
            f"Failed to boot isolated MemoryOS service. Log: {log_file.read_text(errors='replace')[:1000]}"
        )

    return ServiceInstance(process=proc, port=port, token=token, log_file=log_file)


async def _run_smoke_10(atlas_root: Path, mos_root: Path, mos_db: Path, output_path: Path) -> dict[str, Any]:
    os.environ["ATLAS_UNIFIED_EVENT_CLASS"] = "TEST"
    svc = _boot_isolated_memoryos(mos_root, mos_db, atlas_root)

    from atlas import config as atlas_config
    from atlas.config import AtlasConfig
    from atlas.memory.capture import CaptureService
    from atlas.memory.observer import MemoryObserver
    from atlas.memory.observer_drain import MemoryObserverDrain
    from atlas.memory.unified_client import UnifiedMemoryClient
    from atlas.memory.unified_facade import UnifiedMemoryFacade
    from atlas.models import ModelManager

    import atlas.models.manager as model_manager_module

    raw_cfg, _ = _apply_model_config()
    raw_cfg.setdefault("memory", {}).setdefault("unified", {})
    raw_cfg["memory"]["unified"].update({
        "enabled": True,
        "service_url": f"http://127.0.0.1:{svc.port}",
        "internal_token": svc.token,
        "outbox_path": str(atlas_root / "outbox.db"),
    })
    cfg = AtlasConfig(raw_cfg)
    atlas_config.get_config = lambda: cfg
    model_manager_module.get_config = lambda: cfg

    manager = ModelManager()
    client = UnifiedMemoryClient(service_url=f"http://127.0.0.1:{svc.port}", internal_token=svc.token)
    facade = UnifiedMemoryFacade(config=cfg, client=client)
    capture = CaptureService(
        facade=facade, config=cfg, outbox_path=atlas_root / "outbox.db", event_class="TEST",
    )
    outbox = capture._ensure_outbox()
    observer = MemoryObserver(manager, cfg, outbox=outbox)
    drain = MemoryObserverDrain(observer, facade)

    total_input_tokens = 0
    total_output_tokens = 0
    user_statements_formed = 0
    question_or_third_party_user_errors = 0
    case_results: list[dict[str, Any]] = []

    try:
        for idx, case in enumerate(SMOKE_CASES, start=1):
            session_id = f"smoke_session_{idx:02d}_{case['id']}"

            # Step 1: Capture user message
            provenance = {"external_content": True} if case["is_external"] else {}
            msg_id = f"msg_{idx:02d}_user"
            asst_msg_id = f"msg_{idx:02d}_asst"

            capture.capture_user_message(
                session_id, msg_id, case["user_message"],
                occurred_at=f"2026-10-08T01:{idx:02d}:00Z", source_timezone="UTC",
            )
            if case.get("assistant_reply"):
                capture.capture_assistant_message(
                    session_id, asst_msg_id, case["assistant_reply"],
                    occurred_at=f"2026-10-08T01:{idx:02d}:30Z", source_timezone="UTC",
                )

            # Step 2: Flush capture outbox to MemoryOS HTTP service (ACKed capture sources)
            flush_res = await capture.flush()

            # Retrieve ACKed sources for this session
            rows = outbox._conn.execute(
                "SELECT payload_json FROM outbox_events WHERE state = 'ACKED'"
            ).fetchall()
            session_sources = []
            for r in rows:
                data = json.loads(r["payload_json"])
                obs = data.get("observation", data)
                loc = obs.get("locator", {}) or {}
                loc_val = str(loc.get("value") or "")
                if session_id in loc_val or (obs.get("content") or {}).get("session_id") == session_id:
                    if "text" not in obs and isinstance(obs.get("content"), dict):
                        obs["text"] = obs["content"].get("text", "")
                    if case["is_external"]:
                        obs["provenance"] = {"external_content": True}
                    session_sources.append(obs)

            # Step 3: Observer processes ACKed sources using real deepseek-v4.1-flash model
            batch = await observer.add_messages(
                session_id, session_sources, session_ended=True,
                context=facade.default_context(runtime_session_id=session_id),
            )

            batch_meta = {}
            formed_memories: list[dict[str, Any]] = []

            if batch is not None:
                total_input_tokens += batch.input_tokens
                total_output_tokens += batch.output_tokens
                batch_meta = {
                    "batch_id": batch.batch_id,
                    "model_id": batch.model_id,
                    "input_tokens": batch.input_tokens,
                    "output_tokens": batch.output_tokens,
                    "raw_output": batch.raw_output,
                }

                # Step 4: Drain Observer batch to MemoryOS HTTP service (POST /v1/unified/observe)
                await drain.drain_once()

                # Step 5: Verify formed memories and GET /v1/unified/evidence/{ref}
                for obs_item in batch.payload.get("observations", []):
                    obs_speaker = obs_item.get("speaker_role")
                    obs_content = obs_item.get("content", {})
                    obs_text = obs_content.get("text", "")
                    obs_facet = obs_content.get("facet", "")

                    # Check attribution violations:
                    # Case 6 (web content) must NOT be attributed to USER
                    if case["is_external"] and obs_speaker == "USER":
                        question_or_third_party_user_errors += 1

                    # Questions must not be framed as authoritative user factual claims
                    if "是否" in obs_text or "询问" in obs_text or "想知道" in obs_text:
                        if obs_facet in ("FACT", "KNOWLEDGE") and obs_speaker == "USER":
                            # Question was misclassified as user affirmative factual knowledge
                            question_or_third_party_user_errors += 1

                    # Count valid user assertions formed
                    if not case["is_external"] and obs_speaker == "USER":
                        if not any(q in obs_text for q in ("询问", "是否会下雨")):
                            user_statements_formed += 1

                # Query memories formed in isolated SQLite DB for this session
                import sqlite3
                conn = sqlite3.connect(str(mos_db))
                conn.row_factory = sqlite3.Row
                mem_rows = conn.execute(
                    "SELECT id, summary, record_type, status, extra_json FROM memories ORDER BY created_at DESC"
                ).fetchall()
                conn.close()

                for m_row in mem_rows:
                    record_ref = f"memory:{m_row['id']}"
                    # Fetch evidence via HTTP client: GET /v1/unified/evidence/{record_ref}
                    try:
                        ev_resp = await facade.client().evidence(record_ref)
                        evidence_count = ev_resp.get("count", 0)
                        snippets = [s.get("text", "") for s in ev_resp.get("snippets", [])]
                        has_evidence = evidence_count > 0 and len(snippets) > 0
                    except Exception as ev_err:
                        evidence_count = 0
                        snippets = []
                        has_evidence = False

                    formed_memories.append({
                        "record_ref": record_ref,
                        "summary": m_row["summary"],
                        "evidence_openable": has_evidence,
                        "evidence_count": evidence_count,
                        "sample_snippet": snippets[0][:100] if snippets else "",
                    })

            case_result = {
                "case_id": case["id"],
                "title": case["title"],
                "input": case["user_message"],
                "batch": batch_meta,
                "formed_memories_count": len(formed_memories),
                "formed_memories": formed_memories,
            }
            case_results.append(case_result)

            # Write to output JSONL
            with output_path.open("a", encoding="utf-8") as art:
                art.write(json.dumps(case_result, ensure_ascii=False) + "\n")

    finally:
        capture.close()
        await client.aclose()
        svc.close()

    # Criteria validation
    all_evidence_openable = all(
        all(m["evidence_openable"] for m in c["formed_memories"])
        for c in case_results if c["formed_memories"]
    )
    user_statements_passed = user_statements_formed >= 9
    no_misattribution_passed = question_or_third_party_user_errors == 0
    passed = user_statements_passed and no_misattribution_passed and all_evidence_openable

    summary = {
        "status": "completed" if passed else "acceptance_gap",
        "passed": passed,
        "model_id": "deepseek-v4.1-flash",
        "total_cases": len(SMOKE_CASES),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "user_statements_formed": user_statements_formed,
        "question_or_third_party_user_errors": question_or_third_party_user_errors,
        "all_evidence_openable": all_evidence_openable,
        "criteria": {
            "user_statements_formed_ge_9": {
                "threshold": 9,
                "actual": user_statements_formed,
                "passed": user_statements_passed,
            },
            "question_or_third_party_user_errors_eq_0": {
                "threshold": 0,
                "actual": question_or_third_party_user_errors,
                "passed": no_misattribution_passed,
            },
            "all_evidence_openable": {
                "passed": all_evidence_openable,
            },
        },
        "artifact_path": str(output_path),
        "cases": case_results,
    }
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-10", action="store_true", default=True,
                        help="Run the complete 10-dialogue real ModelRouter -> MemoryOS HTTP smoke")
    parser.add_argument("--sources", type=Path,
                        help="Optional UTF-8 JSON with session_id and captured sources")
    parser.add_argument("--output", type=Path,
                        help="JSONL artifact path (defaults under isolated ATLAS_DATA_DIR)")
    parser.add_argument("--post", action="store_true",
                        help="POST real Observer batches to the configured MemoryOS HTTP service")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        atlas_root, mos_root, mos_db, _hermes_home = _ensure_isolated_roots()
        output_path = args.output or (atlas_root / "memory-v1-s2-smoke-10.jsonl")
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        summary = asyncio.run(_run_smoke_10(atlas_root, mos_root, mos_db, output_path))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["passed"] else 1
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "trace": [
                {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
                for f in traceback.extract_tb(exc.__traceback__)[-6:]
            ],
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
