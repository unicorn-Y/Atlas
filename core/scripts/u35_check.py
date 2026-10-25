"""Focused U35 end-to-end backend scenarios; never starts Electron or takes screenshots."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import tempfile
import zipfile
import io
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.api.automation_router import automation_router
from atlas.api.dependencies import get_app_services
from atlas.api.quick_write_router import router as quick_write_router
from atlas.automation import inbox
from atlas.automation.engine import _summarize
from atlas.runtime.history_adapters import inspect_jsonl, normalize_jsonl_messages
from atlas.runtime.media_understanding import extract_document, media_context_block, ocr_image_data_url

ROOT = Path(__file__).resolve().parents[2]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def main_async() -> None:
    print("U35 scenario: 1 reasoning/model-cycle controls are wired to capability metadata", flush=True)
    settings = (ROOT / "frontend/src/renderer/pages/SettingsPage.tsx").read_text(encoding="utf-8")
    app_tsx = (ROOT / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    check("atlas.model-cycle" in settings and "atlas.model-cycle" in app_tsx, "model cycle preference is disconnected")
    check("/fast" in app_tsx and "/thinking" in app_tsx and "supports_reasoning_effort" in app_tsx,
          "reasoning commands do not check model capability")
    check("reasoning_efforts" in app_tsx and "reasoning_effort" in app_tsx,
          "selected effort is not taken from the active model's supported variants")
    print("U35 scenario PASS: 1 capability-aware model controls", flush=True)

    print("U35 scenario: 2 import three external JSONL dialects with stable dedupe keys", flush=True)
    cases = [
        ("pi", {"type": "message", "timestamp": "2026-01-01T00:00:00Z", "message": {"id": "p1", "role": "user", "content": [{"type": "text", "text": "hello"}]}}),
        ("hermes", {"id": "h1", "role": "assistant", "content": "world", "timestamp": "2026-01-01T00:00:01Z"}),
        ("atlas-cli", {"type": "input", "session_id": "s1", "text": "question"}),
    ]
    for fmt, row in cases:
        content = json.dumps(row, ensure_ascii=False)
        parsed = inspect_jsonl(content, "auto")
        check(parsed["format"] == fmt, f"{fmt} auto-detection failed")
        if fmt == "atlas-cli":
            content += "\n" + json.dumps({"type": "final", "session_id": "s1", "text": "answer"})
        messages = normalize_jsonl_messages(content, fmt)
        check(messages and all(message["external_message_key"] for message in messages), f"{fmt} did not normalize")
        check(normalize_jsonl_messages(content, fmt)[0]["external_message_key"] == messages[0]["external_message_key"],
              f"{fmt} dedupe key changed on retry")
    print("U35 scenario PASS: 2 JSONL import adapters", flush=True)

    print("U35 scenario: 3 extract office and text media with auditable context", flush=True)
    text, audit = extract_document("note.txt", "text/plain", "Review the launch plan".encode())
    check("launch plan" in text and audit["sha256"] and "launch plan" in media_context_block(audit, text),
          "text extraction/audit context failed")
    docx_payload = io.BytesIO()
    with zipfile.ZipFile(docx_payload, "w") as archive:
        archive.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>office body</w:t></w:r></w:p></w:body></w:document>")
    docx_text, docx_audit = extract_document("brief.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx_payload.getvalue())
    check("office body" in docx_text and docx_audit["extractor"] == "docx-xml", "DOCX extraction failed")
    png = base64.b64encode(b"not-real-png").decode("ascii")
    _, image_audit = ocr_image_data_url(f"data:image/png;base64,{png}", 0)
    check(image_audit.get("extractor") == "tesseract" and image_audit.get("sha256"), "image OCR audit missing")
    print("U35 scenario PASS: 3 media extraction and source audit", flush=True)

    print("U35 scenario: 4 model-backed quick-write preview redacts credentials", flush=True)
    captured: dict[str, object] = {}

    class FakeRouter:
        async def complete_for(self, model: str, route: str, messages: list[dict[str, str]], **kwargs: object) -> object:
            captured.update(model=model, route=route, prompt=messages[0]["content"], kwargs=kwargs)
            return SimpleNamespace(text="Reviewed draft")

    services = SimpleNamespace(model_mgr=SimpleNamespace(model_router=FakeRouter(), current_model="test-model"), memory=None)
    app = FastAPI()
    app.include_router(quick_write_router)
    app.include_router(automation_router)
    app.dependency_overrides[get_app_services] = lambda: services
    with tempfile.TemporaryDirectory(prefix="atlas-u35-") as directory:
        inbox._PATH = Path(directory) / "data" / "automation-inbox.sqlite3"
        inbox.record_run({"id": "auto-a", "name": "Daily summary", "payload": {"kind": "agent_turn"}}, {
            "run_id": "run-a", "status": "ok", "trigger": "cron", "started_at": "2026-10-25T12:00:00Z",
            "finished_at": "2026-10-25T12:01:00Z", "conversation_id": "automation-auto-a",
            "result": {"text": "Daily report ready", "result_url": "https://example.invalid/report", "conversation_id": "automation-auto-a"},
        })
        inbox.record_run({"id": "auto-b", "name": "Nightly script", "payload": {"kind": "script"}}, {
            "run_id": "run-b", "status": "error", "trigger": "interval", "finished_at": "2026-10-25T13:00:00Z", "error": "exit 2",
            "result": {"stdout": "script output"},
        })
        # Returned DBOS workflow summaries must retain nested result metadata for later history backfill.
        summarized = _summarize({"run_id": "r", "automation_id": "a", "automation_name": "A", "conversation_id": "c",
                                 "status": "ok", "error": "", "delivery": "not-requested", "trigger": "cron",
                                 "started_at": "start", "finished_at": "finish", "result": {"text": "kept"}})
        check(summarized["result"] == {"text": "kept"}, "DBOS history summary discarded the execution result")
        import_run_record = {"id": "auto-c", "name": "Backfilled", "payload": {"kind": "script"}}
        inbox.import_run(import_run_record, {"workflow_id": "workflow-c", "status": "SUCCESS", "created_at": "2026-10-24T00:00:00Z",
                                              "result": {"run_id": "run-c", "status": "ok", "result": {"text": "history result", "conversation_id": "c-id"}}})
        check(inbox.unread_count() == 3, "inbox did not persist live and backfilled runs")
        rows = inbox.list_runs(limit=2, offset=0, status="all", source="all", unread=False)
        check(rows["total"] == 3 and rows["next_offset"] == 2 and rows["runs"][0]["run_key"] == "run-b", "inbox ordering/pagination failed")
        item_a = next(item for item in inbox.list_runs(limit=10, offset=0, status="all", source="all", unread=False)["runs"] if item["run_key"] == "run-a")
        check(item_a["summary"] == "Daily report ready" and item_a["result_url"].endswith("/report") and item_a["conversation_id"] == "automation-auto-a",
              "inbox omitted summary, artifact link, or conversation association")
        check(inbox.list_runs(limit=10, offset=0, status="error", source="script", unread=False)["total"] == 1,
              "inbox status/source filters failed")
        print("U35 scenario PASS: 5 durable cross-automation inbox, filters, paging and per-run read state", flush=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://u35.test") as client:
            response = await client.post("/api/quick-write", json={"action": "rewrite", "selected_text": "Bearer dsk-abcdefghijklmnop123456", "instruction": "clear"})
            check(response.status_code == 200 and response.json()["text"] == "Reviewed draft", "quick-write API did not return a preview")
            check("dsk-abcdefghijklmnop123456" not in str(captured["prompt"]) and "[REDACTED]" in str(captured["prompt"]),
                  "quick-write prompt leaked a credential-like selection")
            response = await client.get("/api/automations/inbox/runs?limit=1&offset=0&status=error&source=script")
            check(response.status_code == 200 and response.json()["total"] == 1, "inbox runs API filter route failed")
            run_key = response.json()["runs"][0]["run_key"]
            response = await client.post("/api/automations/inbox/read", json={"run_ids": [run_key]})
            check(response.status_code == 200 and response.json()["unread"] == 2, "per-run read API failed")
            check((await client.get("/api/automations/inbox/unread-count")).json()["unread"] == 2,
                  "inbox unread-count endpoint failed")
    # The renderer and IPC callsites are checked alongside the live API scenario without launching Electron.
    composer = (ROOT / "frontend/src/renderer/floating-composer.tsx").read_text(encoding="utf-8")
    main = (ROOT / "frontend/src/main/electron.ts").read_text(encoding="utf-8")
    sidebar = (ROOT / "frontend/src/renderer/shell/Sidebar.tsx").read_text(encoding="utf-8")
    check(all(token in composer for token in ("/api/quick-write", "copyResult", "returnDraft", "onFloatingComposerContext")),
          "floating composer preview/copy/context return path is disconnected")
    check("随手写 / 改写选中文字" in main and "return-draft" in main, "selection menu or draft return IPC is disconnected")
    check("automationInboxUnread" in sidebar and "atlas:automation-inbox-unread-changed" in app_tsx,
          "navigation unread count is disconnected")
    print("U35 scenario PASS: 4 quick-write preview/IPC and persistent automation inbox API", flush=True)


def main() -> int:
    asyncio.run(main_async())
    print("Electron was not started; no screenshots were captured.", flush=True)
    print("U35 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
