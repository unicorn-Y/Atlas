"""Real SDK subprocess path for attempt rollback, commit and durable history."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import threading
import time

import pytest

from tests.fakes.fake_llm_provider import (
    DropMidStream, Error, FakeLLMServer, Hang, StallMidStream, Text, ToolCall, write_atlas_home,
)

SDK_ROOT = Path(__file__).resolve().parents[2] / "sdk" / "python"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from atlas_sdk.app_server import AppServer, AppServerError


pytestmark = pytest.mark.unit


def _isolated_app_server_env(
    root: Path, fake: FakeLLMServer, *, with_fallback_model: bool = False,
) -> dict[str, str]:
    data = root / "atlas"
    config = data / "config"
    config.mkdir(parents=True)
    (data / "data").mkdir()
    (data / "data" / "user-settings.json").write_text(
        json.dumps({"fallback_chain": []}), encoding="utf-8",
    )
    fallback = ["fallback-model"] if with_fallback_model else ["fake-model"]
    custom_models = (
        '[[models.custom]]\nid="fake-model"\nname="Fake fixture"\nprovider="openai"\n'
        f'base_url="{fake.base_url}"\nlitellm_model="openai/fake-model"\nmax_output_tokens=512\n'
    )
    if with_fallback_model:
        custom_models += (
            '[[models.custom]]\nid="fallback-model"\nname="Fake fallback fixture"\nprovider="openai"\n'
            f'base_url="{fake.base_url}"\nlitellm_model="openai/fallback-model"\nmax_output_tokens=512\n'
        )
    config_text = (
        f'[models]\ndefault="fake-model"\nfallback={json.dumps(fallback)}\n'
        f'[models.gateway]\nbase_url="{fake.base_url}"\napi_key="sk-fake-e2e"\n'
        + custom_models
        + '[agent]\nengine="hermes"\nverify_before_stop=false\n'
        '[tools]\nauto_start=[]\n[tools.servers]\n[scheduler]\nenabled=false\n'
    )
    (config / "atlas.toml").write_text(
        config_text,
        encoding="utf-8",
    )
    write_atlas_home(data / "engine", fake.base_url, extra_config=(
        "auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n"
        "models:\n  fallback: []\n"
    ))
    for name in ("home", "userprofile", "appdata", "localappdata", "temp", "tmp", "tmpdir"):
        (root / name).mkdir()
    env = dict(os.environ)
    for key in tuple(env):
        upper = key.upper()
        if (any(marker in upper for marker in ("API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL"))
                or upper.startswith("HERMES_SESSION_") or upper.endswith("_PROXY")):
            env.pop(key, None)
    env.update(
        ATLAS_DATA_DIR=str(data), HERMES_HOME=str(data / "engine"),
        ATLAS_SCHEDULER_ENABLED="false", HERMES_TEST_MODE="1",
        OPENAI_API_BASE=fake.base_url, OPENAI_BASE_URL=fake.base_url, OPENAI_API_KEY="sk-fake-e2e",
        HOME=str(root / "home"), USERPROFILE=str(root / "userprofile"),
        APPDATA=str(root / "appdata"), LOCALAPPDATA=str(root / "localappdata"),
        TEMP=str(root / "temp"), TMP=str(root / "tmp"), TMPDIR=str(root / "tmpdir"),
        HTTP_PROXY="http://127.0.0.1:1", HTTPS_PROXY="http://127.0.0.1:1",
        ALL_PROXY="http://127.0.0.1:1", NO_PROXY="127.0.0.1,localhost",
        http_proxy="http://127.0.0.1:1", https_proxy="http://127.0.0.1:1",
        all_proxy="http://127.0.0.1:1", no_proxy="127.0.0.1,localhost",
    )
    env["PYTHONPATH"] = os.pathsep.join((str(Path(__file__).resolve().parents[1]), str(SDK_ROOT)))
    return env


def test_real_sdk_app_server_subprocess_commits_only_new_attempt_and_reopens_audit(tmp_path):
    with FakeLLMServer() as fake:
        responses = iter((
            DropMidStream("OLD answer", after_chars=3),
            Text("NEW answer", chunk_chars=4),
            Text("FOLLOW-UP answer", chunk_chars=5),
        ))
        fake._responder = lambda _record: next(responses)
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"],
            workspace=workspace,
            env=isolated_env,
            request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            events = []
            try:
                result = server.prompt(session.session_id, "exercise sdk subprocess rollback", on_event=events.append)
            except TimeoutError as exc:
                observed_types = [
                    {"type": str(event.get("type") or "unknown"),
                     "status": event.get("status"),
                     "content_prefix": str(event.get("content") or "")[:20],
                     "attempt_id": event.get("attempt_id")}
                    for event in events
                ]
                raise AssertionError(
                    f"SDK prompt timed out; observed_event_types={observed_types}; "
                    f"fake_main_requests={len(fake.main_requests())}"
                ) from exc
            assert result.status == "completed"
            assert result.text == "NEW answer"
            old_events = [event for event in events if event.get("type") == "chunk" and "OLD" in str(event.get("content"))]
            rollbacks = [event for event in events if event.get("type") == "message.rollback"]
            new_events = [event for event in events if event.get("type") == "chunk" and "NEW" in str(event.get("content"))]
            assert old_events
            assert len(rollbacks) == 1
            assert rollbacks[0].get("attempt_id") == old_events[0].get("attempt_id")
            assert new_events
            assert all(event.get("attempt_id") != rollbacks[0].get("attempt_id") for event in new_events)
        finally:
            server.close()

        assert process is not None
        assert process.wait(timeout=0) == 0

        resumed_server = AppServer(
            [sys.executable, "-m", "atlas.cli"],
            workspace=workspace,
            env=isolated_env,
            request_timeout=60,
        ).start()
        resumed_process = resumed_server._process
        try:
            resumed_session = resumed_server.new_session(conversation_id=session.conversation_id)
            assert resumed_session.conversation_id == session.conversation_id
            resumed_result = resumed_server.prompt(resumed_session.session_id, "continue after process restart")
            assert resumed_result.status == "completed"
            assert resumed_result.text == "FOLLOW-UP answer"
        finally:
            resumed_server.close()
        assert resumed_process is not None
        assert resumed_process.wait(timeout=0) == 0

        main_requests = fake.main_requests()
        assert len(main_requests) == 3
        replayed_messages = json.dumps(main_requests[-1].get("messages") or [], ensure_ascii=False)
        assert "NEW answer" in replayed_messages
        assert "OLD answer" not in replayed_messages

        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
            transcript = db.get_messages_as_conversation(session.conversation_id)
            audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
        assistant_text = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
        attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
        assert "NEW answer" in assistant_text
        assert "FOLLOW-UP answer" in assistant_text
        assert all("OLD" not in text for text in assistant_text)
        assert any(row["payload"].get("status") == "discarded"
                   and row["payload"].get("attempt_id") == rollbacks[0].get("attempt_id")
                   and str(row["payload"].get("partial_text") or "").startswith("OLD")
                   for row in attempt_rows)


def test_sdk_app_server_rollback_stays_private_while_retry_waits_for_approval(tmp_path):
    with FakeLLMServer([
        DropMidStream("OLD attempt must not leak into the approval retry", after_chars=12),
        ToolCall("request_permissions", {
            "permission": "workspace.write", "reason": "NEW attempt approval marker",
        }),
        Text("APPROVAL_RETRY_COMPLETED"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        resumed = None
        resumed_process = None
        try:
            session = server.new_session()
            receipt = server.enqueue(
                session.session_id, "retry and request a scoped approval", request_id="oldnew-approval-1",
            )
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1
            approval = pending[0]
            assert approval.kind == "approval"
            assert approval.tool_name == "request_permissions"
            assert approval.arguments == {
                "permission": "workspace.write", "reason": "NEW attempt approval marker",
                "scope": "this request",
            }

            requests = fake.main_requests()
            assert len(requests) == 2
            retry_messages = json.dumps(requests[1].get("messages") or [], ensure_ascii=False)
            assert "OLD attempt must not leak" not in retry_messages

            server.respond_approval(approval.request_id, "allow")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, receipt.request_id).status == "completed"
            assert len(fake.main_requests()) == 3

            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                transcript = db.get_messages_as_conversation(session.conversation_id)
                audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
            transcript_text = "\n".join(str(row.get("content") or "") for row in transcript)
            assert "APPROVAL_RETRY_COMPLETED" in transcript_text
            assert "OLD attempt must not leak" not in transcript_text
            discarded = [row for row in audit if row.get("event_type") == "model/attempt"
                         and row.get("payload", {}).get("status") == "discarded"]
            assert len(discarded) == 1
            assert str(discarded[0]["payload"].get("partial_text") or "") == "OLD attempt "
            approval_states = [row.get("payload", {}).get("state") for row in audit
                               if row.get("event_type") == "appserver.request"
                               and row.get("payload", {}).get("request_id") == approval.request_id]
            assert approval_states == ["pending", "resolved"]
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0
        resumed = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        resumed_process = resumed._process
        try:
            reopened = resumed.new_session(conversation_id=session.conversation_id)
            assert resumed.get_working_directory(reopened.session_id) == str(workspace.resolve())
        finally:
            resumed.close()
        assert resumed_process is not None and resumed_process.wait(timeout=0) == 0


def test_real_sdk_app_server_cancel_rolls_back_partial_attempt_and_persists_only_audit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    with FakeLLMServer([StallMidStream("OLD answer", after_chars=3, seconds=30)]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        tokenizer_cache = Path(tempfile.gettempdir()) / "data-gym-cache"
        tokenizer_asset = tokenizer_cache / hashlib.sha1(
            b"https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
        ).hexdigest()
        if not tokenizer_asset.is_file():
            pytest.skip("offline app-server cancellation probe requires the pre-cached public cl100k tokenizer asset")
        isolated_env["TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"],
            workspace=workspace,
            env=isolated_env,
            request_timeout=60,
        ).start()
        process = server._process
        prompt_future = None
        process_exit_before_close = None
        events = []
        events_lock = threading.Lock()
        old_seen = threading.Event()
        close_duration = None

        def capture_event(event):
            with events_lock:
                events.append(dict(event))
            if event.get("type") == "chunk" and "OLD" in str(event.get("content") or ""):
                old_seen.set()

        try:
            session = server.new_session()
            with ThreadPoolExecutor(max_workers=1) as executor:
                prompt_future = executor.submit(
                    server.prompt, session.session_id, "cancel after the OLD attempt starts",
                    on_event=capture_event,
                )
                assert old_seen.wait(timeout=20), {
                    "provider_requests": len(fake.main_requests()),
                    "event_types": [event.get("type") for event in events],
                }
                assert len(fake.main_requests()) == 1
                cancellation = server._request(
                    "session/cancel", {"session_id": session.session_id},
                )
                assert cancellation.get("cancelled") is True
                result = prompt_future.result(timeout=20)
                server.wait(session.session_id)
                server.close_session(session.session_id)
                server._request("shutdown", {})
                process_exit_before_close = process.poll()
        finally:
            if prompt_future is not None and not prompt_future.done():
                try:
                    server._request("session/cancel", {"session_id": session.session_id})
                    prompt_future.result(timeout=20)
                except Exception:
                    pass
            close_started = time.monotonic()
            server.close()
            close_duration = time.monotonic() - close_started

        stderr_lines = [str(line) for line in list(server._stderr_tail)]
        stderr_summary = [
            f"frame:{match.group(1)}"
            for line in stderr_lines
            if (match := re.search(r"line\s+\d+,\s+in\s+([A-Za-z_][A-Za-z0-9_.]*)", line))
        ][-15:]
        if any("tiktoken" in line.lower() for line in stderr_lines):
            stderr_summary.append("failure_path: tokenizer encoding asset fetch")
        if any("ProxyError:" in line for line in stderr_lines):
            stderr_summary.append("exception: ProxyError to externally hosted tokenizer asset, blocked by isolated test proxy")
        assert process is not None and process.wait(timeout=0) == 0, {
            "process_exit": process.poll(),
            "process_exit_before_close": process_exit_before_close,
            "close_duration_seconds": close_duration,
            "stderr_summary": stderr_summary[-20:],
        }
        assert result.status == "cancelled"
        assert result.text == ""
        with events_lock:
            observed = list(events)
        old_chunk_index = next(
            index for index, event in enumerate(observed)
            if event.get("type") == "chunk" and "OLD" in str(event.get("content") or "")
        )
        rollback_indexes = [
            index for index, event in enumerate(observed)
            if event.get("type") == "message.rollback"
        ]
        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
            transcript = db.get_messages_as_conversation(session.conversation_id)
            audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
        attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
        assert rollback_indexes, {
            "event_types": [event.get("type") for event in observed],
            "attempt_audit": [
                ((row.get("payload") or {}).get("status"),
                 (row.get("payload") or {}).get("category"))
                for row in attempt_rows
            ],
        }
        rollback_index = rollback_indexes[0]
        old_attempt = observed[old_chunk_index].get("attempt_id")
        assert old_attempt
        assert rollback_index > old_chunk_index
        assert observed[rollback_index].get("attempt_id") == old_attempt
        assert observed[rollback_index].get("category") == "cancelled"
        assert len(fake.main_requests()) == 1

        assistant_text = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
        assert all("OLD" not in content for content in assistant_text)
        assert any(row["payload"].get("status") == "discarded"
                   and row["payload"].get("category") == "cancelled"
                   and row["payload"].get("attempt_id") == old_attempt
                   and str(row["payload"].get("partial_text") or "").startswith("OLD")
                   for row in attempt_rows)


def test_sdk_app_server_fallback_attempt_isolated_across_process_restart(tmp_path):
    with FakeLLMServer() as fake:
        responses = iter((
            Text("OLD filtered answer", finish_reason="content_filter"),
            Text("NEW fallback answer", chunk_chars=4),
            Text("FOLLOW-UP answer", chunk_chars=5),
        ))
        fake._responder = lambda _record: next(responses)
        isolated_env = _isolated_app_server_env(tmp_path, fake, with_fallback_model=True)
        isolated_env.update(
            CLAUDE_CODE_MAX_RETRIES="0",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="30",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        first_process = server._process
        events = []
        try:
            session = server.new_session()
            result = server.prompt(
                session.session_id, "exercise SDK fallback attempt isolation", on_event=events.append,
            )
            assert result.status == "completed"
            assert result.text == "NEW fallback answer"
            rollback = next(event for event in events if event.get("type") == "message.rollback")
            rollback_index = events.index(rollback)
            chunks = [(index, event) for index, event in enumerate(events) if event.get("type") == "chunk"]
            old_chunks = [(index, event) for index, event in chunks if index < rollback_index]
            new_chunks = [(index, event) for index, event in chunks if index > rollback_index]
            old_stream = "".join(str(event.get("content") or "") for _, event in old_chunks)
            new_stream = "".join(str(event.get("content") or "") for _, event in new_chunks)
            assert "OLD filtered answer" in old_stream
            assert all(event.get("attempt_id") == rollback.get("attempt_id") for _, event in old_chunks)
            assert "NEW fallback answer" in new_stream
            assert all(event.get("attempt_id") != rollback.get("attempt_id") for _, event in new_chunks)
            assert all(event.get("attempt_id") != rollback.get("attempt_id") for _, event in new_chunks)
        finally:
            server.close()
        assert first_process is not None and first_process.wait(timeout=0) == 0

        resumed_server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        resumed_process = resumed_server._process
        try:
            resumed_session = resumed_server.new_session(conversation_id=session.conversation_id)
            assert resumed_session.conversation_id == session.conversation_id
            resumed = resumed_server.prompt(resumed_session.session_id, "continue after fallback restart")
            assert resumed.status == "completed"
            assert resumed.text == "FOLLOW-UP answer"
        finally:
            resumed_server.close()
        assert resumed_process is not None and resumed_process.wait(timeout=0) == 0

        requests = fake.main_requests()
        assert [request["model"] for request in requests] == [
            "fake-model", "fallback-model", "fake-model",
        ]
        replayed = json.dumps(requests[-1].get("messages") or [], ensure_ascii=False)
        assert "NEW fallback answer" in replayed
        assert "OLD filtered answer" not in replayed

        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
            transcript = db.get_messages_as_conversation(session.conversation_id)
            audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
        assistant_text = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
        assert "NEW fallback answer" in assistant_text
        assert "FOLLOW-UP answer" in assistant_text
        assert all("OLD filtered answer" not in text for text in assistant_text)
        attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
        assert any(
            row["payload"].get("status") == "discarded"
            and row["payload"].get("attempt_id") == rollback.get("attempt_id")
            and str(row["payload"].get("partial_text") or "").startswith("OLD filtered answer")
            for row in attempt_rows
        )


def test_sdk_app_server_retry_keeps_max_output_continuation_across_restart(tmp_path):
    with FakeLLMServer() as fake:
        responses = iter((
            DropMidStream("OLD answer", after_chars=3),
            Text("NEW answer", chunk_chars=4, finish_reason="length"),
            Text("continuation completed", chunk_chars=5),
            Text("FOLLOW-UP answer", chunk_chars=5),
        ))
        fake._responder = lambda _record: next(responses)
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="1",
            CLAUDE_CODE_MAX_RETRIES="0",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="30",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            events = []
            result = server.prompt(
                session.session_id, "retry the failed attempt and complete the limited answer",
                on_event=events.append,
            )
            assert result.status == "completed"
            assert result.text == "NEW answercontinuation completed"
            rollback = next(event for event in events if event.get("type") == "message.rollback")
            rollback_index = events.index(rollback)
            chunks = [(index, event) for index, event in enumerate(events) if event.get("type") == "chunk"]
            old_chunks = [(index, event) for index, event in chunks if index < rollback_index]
            accepted_chunks = [(index, event) for index, event in chunks if index > rollback_index]
            assert old_chunks
            assert all(event.get("attempt_id") == rollback.get("attempt_id") for _, event in old_chunks)
            assert "OLD" in "".join(str(event.get("content") or "") for _, event in old_chunks)
            accepted_text = "".join(str(event.get("content") or "") for _, event in accepted_chunks)
            assert "NEW answer" in accepted_text
            assert "continuation completed" in accepted_text
            assert all(event.get("attempt_id") != rollback.get("attempt_id")
                       for _, event in accepted_chunks)
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0

        requests = fake.main_requests()
        assert len(requests) == 3
        continuation_messages = requests[2].get("messages") or []
        continuation_context = json.dumps(continuation_messages, ensure_ascii=False)
        assert "NEW answer" in continuation_context
        assert "Output token limit hit" in continuation_context

        resumed_server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        resumed_process = resumed_server._process
        try:
            resumed_session = resumed_server.new_session(conversation_id=session.conversation_id)
            assert resumed_session.conversation_id == session.conversation_id
            follow_up = resumed_server.prompt(resumed_session.session_id, "continue after restart")
            assert follow_up.status == "completed"
            assert follow_up.text == "FOLLOW-UP answer"
        finally:
            resumed_server.close()
        assert resumed_process is not None and resumed_process.wait(timeout=0) == 0

        requests = fake.main_requests()
        assert len(requests) == 4
        replayed = json.dumps(requests[3].get("messages") or [], ensure_ascii=False)
        assert "NEW answer" in replayed
        assert "continuation completed" in replayed
        assert "OLD answer" not in replayed

        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
            transcript = db.get_messages_as_conversation(session.conversation_id)
            audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
        assistant_text = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
        assert "NEW answer" in assistant_text
        assert "continuation completed" in assistant_text
        assert "FOLLOW-UP answer" in assistant_text
        assert all("OLD" not in text for text in assistant_text)
        attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
        assert any(row["payload"].get("status") == "discarded"
                   and row["payload"].get("attempt_id") == rollback.get("attempt_id")
                   and str(row["payload"].get("partial_text") or "").startswith("OLD")
                   for row in attempt_rows)


def test_sdk_app_server_discards_partial_tool_arguments_before_retry_and_replay(tmp_path):
    target = tmp_path / "must-not-be-written-by-discarded-sdk-attempt.txt"
    partial_arguments = f'{{"path":{json.dumps(str(target))},"content":"OLD partial side effect'
    with FakeLLMServer() as fake:
        responses = iter((
            DropMidStream(
                "OLD answer", after_chars=3,
                partial_tool_calls=[{
                    "id": "failed-write", "name": "write_file", "arguments": partial_arguments,
                }],
            ),
            Text("NEW answer", chunk_chars=4, finish_reason="length"),
            Text("continuation completed", chunk_chars=5),
            Text("FOLLOW-UP answer", chunk_chars=5),
        ))
        fake._responder = lambda _record: next(responses)
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="1",
            CLAUDE_CODE_MAX_RETRIES="0",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="30",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            events = []
            result = server.prompt(
                session.session_id, "discard malformed tool arguments and finish the answer",
                on_event=events.append,
            )
            assert result.status == "completed"
            assert result.text == "NEW answercontinuation completed"
            rollback = next(event for event in events if event.get("type") == "message.rollback")
            rollback_index = events.index(rollback)
            chunks = [(index, event) for index, event in enumerate(events) if event.get("type") == "chunk"]
            old_chunks = [(index, event) for index, event in chunks if index < rollback_index]
            accepted_chunks = [(index, event) for index, event in chunks if index > rollback_index]
            assert old_chunks and "OLD" in "".join(str(event.get("content") or "") for _, event in old_chunks)
            assert all(event.get("attempt_id") == rollback.get("attempt_id") for _, event in old_chunks)
            assert "NEW answer" in "".join(str(event.get("content") or "") for _, event in accepted_chunks)
            assert "continuation completed" in "".join(
                str(event.get("content") or "") for _, event in accepted_chunks
            )
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0

        assert not target.exists(), "discarded partial write_file arguments must never execute"
        requests = fake.main_requests()
        assert len(requests) == 3
        retry_history = json.dumps(requests[1].get("messages") or [], ensure_ascii=False)
        assert "OLD answer" not in retry_history
        assert "failed-write" not in retry_history
        continuation_history = json.dumps(requests[2].get("messages") or [], ensure_ascii=False)
        assert "NEW answer" in continuation_history
        assert "Output token limit hit" in continuation_history
        assert "OLD answer" not in continuation_history
        assert "failed-write" not in continuation_history

        resumed_server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        resumed_process = resumed_server._process
        try:
            resumed_session = resumed_server.new_session(conversation_id=session.conversation_id)
            follow_up = resumed_server.prompt(resumed_session.session_id, "continue after restart")
            assert follow_up.status == "completed"
            assert follow_up.text == "FOLLOW-UP answer"
        finally:
            resumed_server.close()
        assert resumed_process is not None and resumed_process.wait(timeout=0) == 0

        replayed = json.dumps(fake.main_requests()[3].get("messages") or [], ensure_ascii=False)
        assert "NEW answer" in replayed
        assert "continuation completed" in replayed
        assert "OLD answer" not in replayed
        assert "failed-write" not in replayed

        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
            transcript = db.get_messages_as_conversation(session.conversation_id)
            audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
        assistant_text = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
        assert any("NEW answer" in text for text in assistant_text)
        assert any("continuation completed" in text for text in assistant_text)
        assert any("FOLLOW-UP answer" in text for text in assistant_text)
        assert all("OLD" not in text for text in assistant_text)
        attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
        assert any(row["payload"].get("status") == "discarded"
                   and row["payload"].get("attempt_id") == rollback.get("attempt_id")
                   and str(row["payload"].get("partial_text") or "").startswith("OLD")
                   for row in attempt_rows)


def test_sdk_durable_enqueue_receipt_is_idempotent_across_app_server_restart(tmp_path):
    with FakeLLMServer([Text("unused")]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        first_process = first._process
        try:
            session = first.new_session()
            receipt = first.enqueue(session.session_id, "queued user prompt", request_id="lost-receipt-1")
        finally:
            first.close()
        assert first_process is not None and first_process.wait(timeout=0) == 0

        second = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        second_process = second._process
        try:
            reopened = second.new_session(conversation_id=session.conversation_id)
            duplicate = second.enqueue(reopened.session_id, "queued user prompt", request_id="lost-receipt-1")
            assert duplicate.conversation_id == receipt.conversation_id == session.conversation_id
            assert duplicate.request_id == receipt.request_id
            assert duplicate.event_id == receipt.event_id
            assert duplicate.session_id == reopened.session_id
            with pytest.raises(AppServerError, match="different payload"):
                second.enqueue(reopened.session_id, "changed queued prompt", request_id="lost-receipt-1")
        finally:
            second.close()
        assert second_process is not None and second_process.wait(timeout=0) == 0

        from atlas.engine.session_sync import read_session_events

        rows = read_session_events(
            tmp_path / "atlas" / "engine", session.conversation_id, after_seq=0, limit=100,
        )
        enqueued = [row for row in rows if row.get("event_type") == "inbox.enqueued"
                    and (row.get("payload") or {}).get("request_id") == "lost-receipt-1"]
        assert len(enqueued) == 1
        assert enqueued[0]["payload"]["content"] == "queued user prompt"
        assert enqueued[0]["payload"]["lane"] == "next-turn"


def test_sdk_enqueue_starts_worker_without_sync_prompt_and_waits_for_commit(tmp_path):
    with FakeLLMServer([Text("AUTONOMOUS_OK")]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            receipt = server.enqueue(
                session.session_id, "queued only once", request_id="worker-once-1",
            )
            # Wait through the public SDK surface without a synchronous prompt wake.
            assert server.wait(session.session_id) is None

            requests = fake.main_requests()
            assert len(requests) == 1, "durable enqueue must start exactly one model run"
            messages_json = json.dumps(requests[0].get("messages") or [], ensure_ascii=False)
            assert messages_json.count("queued only once") == 1

            duplicate = server.enqueue(
                session.session_id, "queued only once", request_id="worker-once-1",
            )
            assert duplicate.event_id == receipt.event_id
            assert len(fake.main_requests()) == 1

            from atlas.engine.session_sync import read_session_events

            rows = read_session_events(
                tmp_path / "atlas" / "engine", session.conversation_id,
                after_seq=0, limit=1000,
            )
            consumed = [
                row for row in rows
                if row.get("event_type") == "inbox.consumed"
                and (row.get("payload") or {}).get("event_id") == receipt.event_id
            ]
            assert len(consumed) == 1
            committed = [
                row for row in rows
                if row.get("event_type") == "model/attempt"
                and (row.get("payload") or {}).get("status") == "committed"
            ]
            assert committed
            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                transcript = db.get_messages_as_conversation(session.conversation_id)
            assistant_text = [str(row.get("content") or "") for row in transcript
                              if row.get("role") == "assistant"]
            assert "AUTONOMOUS_OK" in assistant_text
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_app_server_worker_does_not_replay_started_head_item(tmp_path):
    with FakeLLMServer([Text("must stay unused")]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            from atlas.engine.kernel.inbox import DurableInbox

            inbox = DurableInbox(
                tmp_path / "atlas" / "engine", session.conversation_id,
            )
            async def seed_started_item():
                event_id = await inbox.inject(
                    "old in-flight prompt", lane="next-turn", request_id="old-worker-req",
                )
                assert await inbox.mark_started(
                    event_id, lane="next-turn", run_id="old-worker-run",
                ) is True
                return event_id

            old_event_id = asyncio.run(seed_started_item())
            receipt = server.enqueue(
                session.session_id, "new queued prompt", request_id="new-worker-req",
            )
            server.wait(session.session_id)

            assert len(fake.main_requests()) == 0
            from atlas.engine.session_sync import read_session_events

            rows = read_session_events(
                tmp_path / "atlas" / "engine", session.conversation_id,
                after_seq=0, limit=1000,
            )
            assert any(
                row.get("event_type") == "inbox.started"
                and (row.get("payload") or {}).get("event_id") == old_event_id
                and (row.get("payload") or {}).get("run_id") == "old-worker-run"
                for row in rows
            )
            assert any(
                row.get("event_type") == "inbox.enqueued"
                and (row.get("payload") or {}).get("event_id") == receipt.event_id
                for row in rows
            )
            assert not any(
                row.get("event_type") == "inbox.consumed"
                and (row.get("payload") or {}).get("event_id") in {old_event_id, receipt.event_id}
                for row in rows
            )
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_sdk_replays_durable_session_events_by_cursor_after_cli_restart(tmp_path):
    with FakeLLMServer([Text("CURSOR_REPLAY_OK")]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        first_process = first._process
        try:
            session = first.new_session()
            first.enqueue(session.session_id, "durable cursor prompt", request_id="cursor-req-1")
            first.wait(session.session_id)
            first_page = first.session_events(session.session_id, after_seq=0, limit=2)
            assert first_page.session_id == session.session_id
            assert first_page.conversation_id == session.conversation_id
            assert len(first_page.events) == 2
            first_kinds = [row.event_type for row in first_page.events]
            assert "inbox.enqueued" in first_kinds
            assert "appserver.task" in first_kinds
            cursor = first_page.next_cursor
            assert type(cursor) is int and cursor > 0
            first_seqs = [row.seq for row in first_page.events]
            assert first_seqs == sorted(set(first_seqs))
        finally:
            first.close()
        assert first_process is not None and first_process.wait(timeout=0) == 0

        second = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        second_process = second._process
        try:
            reopened = second.new_session(conversation_id=session.conversation_id)
            page = second.session_events(reopened.session_id, after_seq=cursor, limit=100)
            assert page.session_id == reopened.session_id
            assert page.conversation_id == session.conversation_id
            events = page.events
            seqs = [row.seq for row in events]
            assert seqs == sorted(set(seqs))
            assert all(seq > cursor for seq in seqs)
            kinds = [row.event_type for row in events]
            assert "inbox.started" in kinds
            assert "model/attempt" in kinds
            assert "inbox.consumed" in kinds
            assert set(first_seqs).isdisjoint(seqs)
            assert len(fake.main_requests()) == 1
            with pytest.raises(AppServerError, match="unknown session"):
                second._request("session/events", {
                    "session_id": "missing-session", "after_seq": cursor, "limit": 10,
                })
            with pytest.raises(AppServerError, match="after_seq or limit"):
                second._request("session/events", {
                    "session_id": reopened.session_id, "after_seq": True, "limit": 10,
                })
            with pytest.raises(AppServerError, match="after_seq or limit"):
                second._request("session/events", {
                    "session_id": reopened.session_id, "after_seq": cursor, "limit": 0,
                })
        finally:
            second.close()
        assert second_process is not None and second_process.wait(timeout=0) == 0


def test_app_server_keeps_session_fifo_while_other_session_runs_independently(tmp_path):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    other_session_started = threading.Event()

    def responder(record):
        messages = record["body"].get("messages") or []
        last_user = next((row.get("content") for row in reversed(messages)
                          if row.get("role") == "user"), "")
        value = str(last_user)
        if "A_FIRST_FIFO_MARKER" in value:
            first_started.set()
            if not release_first.wait(timeout=20):
                return Error(status=503, message="test gate deadline expired")
            return Text("A_FIRST_DONE")
        if "A_SECOND_FIFO_MARKER" in value:
            second_started.set()
            return Text("A_SECOND_DONE")
        if "B_INDEPENDENT_MARKER" in value:
            other_session_started.set()
            return Text("B_INDEPENDENT_DONE")
        return Error(status=400, message="unexpected test prompt")

    with FakeLLMServer(responder) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session_a = server.new_session()
            session_b = server.new_session()
            server.enqueue(session_a.session_id, "A_FIRST_FIFO_MARKER", request_id="a-first")
            assert first_started.wait(timeout=20), "first session A request did not reach provider"

            server.enqueue(session_a.session_id, "A_SECOND_FIFO_MARKER", request_id="a-second")
            server.enqueue(session_b.session_id, "B_INDEPENDENT_MARKER", request_id="b-only")
            server.wait(session_b.session_id)

            assert other_session_started.is_set(), "session B did not run while session A was held"
            assert not second_started.is_set(), "session A FIFO head was bypassed"
            assert server.task_status(session_a.session_id, "a-first").status == "running"
            assert server.task_status(session_a.session_id, "a-second").status == "queued"
            assert server.task_status(session_b.session_id, "b-only").status == "completed"

            release_first.set()
            server.wait(session_a.session_id)
            assert second_started.is_set(), "session A second task did not run after the first settled"
            assert server.task_status(session_a.session_id, "a-first").status == "completed"
            assert server.task_status(session_a.session_id, "a-second").status == "completed"

            requests = fake.main_requests()
            prompts = [next((str(row.get("content") or "") for row in reversed(item["messages"])
                             if row.get("role") == "user"), "") for item in requests]
            assert len(requests) == 3
            assert [next(marker for marker in (
                "A_FIRST_FIFO_MARKER", "A_SECOND_FIFO_MARKER", "B_INDEPENDENT_MARKER",
            ) if marker in prompt) for prompt in prompts] == [
                "A_FIRST_FIFO_MARKER", "B_INDEPENDENT_MARKER", "A_SECOND_FIFO_MARKER",
            ]

            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                transcript_a = db.get_messages_as_conversation(session_a.conversation_id)
                transcript_b = db.get_messages_as_conversation(session_b.conversation_id)
                events_a = db.list_session_events(session_a.conversation_id, after_seq=0, limit=1000)
                events_b = db.list_session_events(session_b.conversation_id, after_seq=0, limit=1000)
            text_a = "\n".join(str(row.get("content") or "") for row in transcript_a)
            text_b = "\n".join(str(row.get("content") or "") for row in transcript_b)
            assert "A_FIRST_DONE" in text_a and "A_SECOND_DONE" in text_a
            assert "B_INDEPENDENT_DONE" in text_b
            event_request_ids_a = {
                row.get("payload", {}).get("request_id") for row in events_a
                if isinstance(row.get("payload"), dict)
            }
            event_request_ids_b = {
                row.get("payload", {}).get("request_id") for row in events_b
                if isinstance(row.get("payload"), dict)
            }
            assert {"a-first", "a-second"} <= event_request_ids_a
            assert "b-only" in event_request_ids_b
            assert "b-only" not in event_request_ids_a
            assert not ({"a-first", "a-second"} & event_request_ids_b)
        finally:
            release_first.set()
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


@pytest.mark.parametrize(
    ("failed_event_type", "failed_state"),
    [("inbox.enqueued", ""), ("appserver.task", "queued")],
)
def test_app_server_event_append_failure_returns_no_receipt_then_retries_once(
    tmp_path, failed_event_type, failed_state,
):
    with FakeLLMServer([Text("PERSISTED_AFTER_RETRY")]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        fault_root = tmp_path / "child-fault-injection"
        fault_root.mkdir()
        fail_marker = fault_root / "append-failed.once"
        (fault_root / "sitecustomize.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "from atlas.engine import session_sync\n"
            "_append = session_sync.append_session_event\n"
            "_append_inbox = session_sync.append_inbox_enqueue_with_receipt\n"
            "_target = os.environ.get('ATLAS_TEST_FAIL_EVENT_TYPE', '')\n"
            "_state = os.environ.get('ATLAS_TEST_FAIL_EVENT_STATE', '')\n"
            "_marker = Path(os.environ['ATLAS_TEST_FAIL_EVENT_MARKER'])\n"
            "def _append_once(home, conversation_id, event_type, payload):\n"
            "    if (event_type == _target and (not _state or payload.get('state') == _state)\n"
            "            and not _marker.exists()):\n"
            "        _marker.write_text('injected', encoding='utf-8')\n"
            "        raise OSError('test-only SessionDB event append failure')\n"
            "    return _append(home, conversation_id, event_type, payload)\n"
            "session_sync.append_session_event = _append_once\n"
            "def _append_inbox_once(home, conversation_id, payload):\n"
            "    if _target == 'inbox.enqueued' and not _marker.exists():\n"
            "        _marker.write_text('injected', encoding='utf-8')\n"
            "        raise OSError('test-only SessionDB event append failure')\n"
            "    return _append_inbox(home, conversation_id, payload)\n"
            "session_sync.append_inbox_enqueue_with_receipt = _append_inbox_once\n",
            encoding="utf-8",
        )
        isolated_env["PYTHONPATH"] = os.pathsep.join((
            str(fault_root), isolated_env.get("PYTHONPATH", ""),
        ))
        isolated_env["ATLAS_TEST_FAIL_EVENT_TYPE"] = failed_event_type
        isolated_env["ATLAS_TEST_FAIL_EVENT_STATE"] = failed_state
        isolated_env["ATLAS_TEST_FAIL_EVENT_MARKER"] = str(fail_marker)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            with pytest.raises(AppServerError):
                server.enqueue(session.session_id, "event retry prompt", request_id="fault-once")
            assert fail_marker.exists(), "child process did not inject the requested event failure"
            assert fake.main_requests() == [], "provider ran before a durable enqueue receipt"

            receipt = server.enqueue(session.session_id, "event retry prompt", request_id="fault-once")
            assert receipt.request_id == "fault-once"
            assert receipt.status == "queued"
            server.wait(session.session_id)
            assert server.task_status(session.session_id, "fault-once").status == "completed"
            assert len(fake.main_requests()) == 1

            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                rows = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
                transcript = db.get_messages_as_conversation(session.conversation_id)
            enqueued = [row for row in rows if row.get("event_type") == "inbox.enqueued"
                        and row.get("payload", {}).get("request_id") == "fault-once"]
            assert len(enqueued) == 1
            task_states = [row.get("payload", {}).get("state") for row in rows
                           if row.get("event_type") == "appserver.task"
                           and row.get("payload", {}).get("request_id") == "fault-once"]
            assert task_states[-1] == "completed"
            assert "PERSISTED_AFTER_RETRY" in "\n".join(
                str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"
            )
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def _wait_for_app_server_pending_request(server, session_id: str, fake: FakeLLMServer):
    fake.wait_for_requests(1, timeout=30)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        requests = server.pending_requests(session_id)
        pending = [item for item in requests if item.status == "pending"]
        if pending:
            return pending
        time.sleep(0.1)
    events = server.session_events(session_id, limit=100).events
    event_types = [event.event_type for event in events]
    raise AssertionError(
        "app-server did not persist the model's pending request before the deadline; "
        f"provider_requests={len(fake.main_requests())}, "
        f"provider_request_kinds={[row.get('kind') for row in fake.requests]}, "
        f"process_exit={server._process.poll() if server._process else None}, "
        f"durable_event_types={event_types}"
    )


@pytest.mark.parametrize("kind", ["input", "approval"])
def test_app_server_pending_request_reconnects_in_same_process(tmp_path, kind):
    if kind == "input":
        scripted = [ToolCall("ask_user", {"question": "Which value?", "options": ["A", "B"]}), Text("INPUT_RESUMED")]
    else:
        scripted = [ToolCall("request_permissions", {
            "permission": "workspace.write", "reason": "write requested output",
        }), Text("APPROVAL_RESUMED")]
    with FakeLLMServer(scripted) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            task_id = f"pending-{kind}"
            server.enqueue(session.session_id, "enqueue and reconnect", request_id=task_id)
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1
            request = pending[0]
            assert server.task_status(session.session_id, task_id).status == "running"
            assert request.kind == kind
            if kind == "input":
                assert request.prompt == "Which value?"
                server.respond_input(request.request_id, "B")
            else:
                assert request.tool_name == "request_permissions"
                server.respond_approval(request.request_id, "allow")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, task_id).status == "completed"
            assert server.cancel_task(session.session_id, task_id).status == "too_late"
            assert len(fake.main_requests()) == 2
            request_events = [
                item.payload for item in server.session_events(
                    session.session_id, limit=100,
                ).events
                if item.event_type == "appserver.request"
                and item.payload.get("request_id") == request.request_id
            ]
            assert [item.get("state") for item in request_events] == ["pending", "resolved"]
            assert all(set(item) <= {
                "request_id", "session_id", "kind", "state", "instance_id",
            } for item in request_events)
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_app_server_task_cancel_waits_for_worker_cleanup_and_cancels_queued_item(tmp_path):
    with FakeLLMServer([
        ToolCall("ask_user", {"question": "Wait before continuing?"}),
        Text("must not run after cancellation"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            server.enqueue(session.session_id, "first waits for input", request_id="task-running")
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1 and pending[0].kind == "input"
            assert server.task_status(session.session_id, "task-running").status == "running"

            server.request_timeout = 0.2
            with pytest.raises(TimeoutError):
                server.wait(session.session_id)
            server.request_timeout = 60
            assert server.task_status(session.session_id, "task-running").status == "running"

            server.enqueue(session.session_id, "second must remain queued", request_id="task-queued")
            assert server.task_status(session.session_id, "task-queued").status == "queued"
            assert server.cancel_task(session.session_id, "task-queued").status == "cancelled"

            cancellation = server.cancel_task(session.session_id, "task-running")
            assert cancellation.status == "cancelled"
            assert server.task_status(session.session_id, "task-running").status == "cancelled"
            assert server.task_status(session.session_id, "task-queued").status == "cancelled"
            assert len(fake.main_requests()) == 1
            pending_after = server.pending_requests(session.session_id)
            assert any(item.request_id == pending[0].request_id and item.status == "invalidated"
                       for item in pending_after)
            audit = [item.payload for item in server.session_events(
                session.session_id, limit=100,
            ).events if item.event_type == "appserver.task"]
            first_states = [row.get("state") for row in audit
                            if row.get("request_id") == "task-running"]
            second_states = [row.get("state") for row in audit
                             if row.get("request_id") == "task-queued"]
            assert first_states == ["queued", "running", "cancelling", "cancelled"]
            assert second_states == ["queued", "cancelled"]
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_app_server_task_status_preserves_provider_failure_terminal(tmp_path):
    with FakeLLMServer([Error(status=500, message="fixture failure") for _ in range(8)]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="0",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="1",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="10",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            server.enqueue(session.session_id, "fail exactly once", request_id="task-failed")
            server.wait(session.session_id)
            status = server.task_status(session.session_id, "task-failed").status
            assert status == "failed", f"status={status}, provider_requests={len(fake.main_requests())}"
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_app_server_failed_retry_keeps_old_partial_only_in_attempt_audit(tmp_path):
    with FakeLLMServer([
        DropMidStream("OLD content before retry failure", after_chars=10),
        *[Error(status=500, message="fixture retry failure") for _ in range(8)],
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="0",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="10",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            server.enqueue(session.session_id, "retain only failure audit", request_id="oldnew-failed-retry-1")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, "oldnew-failed-retry-1").status == "failed"
            requests = fake.main_requests()
            assert len(requests) >= 2, "retry provider failure did not occur after the OLD partial stream"

            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                transcript = db.get_messages_as_conversation(session.conversation_id)
                audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
            assistant_text = "\n".join(str(row.get("content") or "") for row in transcript
                                         if row.get("role") == "assistant")
            assert "OLD content before retry failure" not in assistant_text
            attempts = [row["payload"] for row in audit if row.get("event_type") == "model/attempt"]
            discarded = [row for row in attempts if row.get("status") == "discarded"]
            assert any(str(row.get("partial_text") or "") == "OLD conten" for row in discarded)
            assert not any(row.get("status") == "committed"
                           and "OLD" in str(row.get("partial_text") or "") for row in attempts)
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_app_server_provider_timeout_keeps_old_partial_only_in_attempt_audit(tmp_path):
    provider_attempt = 0

    def drop_then_stall(_request):
        nonlocal provider_attempt
        provider_attempt += 1
        if provider_attempt == 1:
            return DropMidStream("OLD timeout partial must not commit", after_chars=12)
        return Hang(seconds=8)

    with FakeLLMServer(drop_then_stall) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="0",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="8",
        )
        config_path = tmp_path / "atlas" / "config" / "atlas.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n[models.provider_timeouts.openai]\nread=1\n",
            encoding="utf-8",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=30,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            server.enqueue(session.session_id, "timeout after an OLD stream", request_id="oldnew-timeout-1")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, "oldnew-timeout-1").status == "failed"
            assert len(fake.main_requests()) >= 2

            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                transcript = db.get_messages_as_conversation(session.conversation_id)
                audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
            assistant_text = "\n".join(str(row.get("content") or "") for row in transcript
                                         if row.get("role") == "assistant")
            assert "OLD timeout partial must not commit" not in assistant_text
            attempts = [row["payload"] for row in audit if row.get("event_type") == "model/attempt"]
            assert any(row.get("status") == "discarded" and row.get("partial_text") == "OLD timeout "
                       for row in attempts)
            assert not any(row.get("status") == "committed"
                           and "OLD" in str(row.get("partial_text") or "") for row in attempts)
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


def test_sdk_prompt_callback_failure_cancels_rolled_back_run_before_reusing_session(tmp_path):
    with FakeLLMServer([
        DropMidStream("OLD answer before input wait", after_chars=10),
        ToolCall("ask_user", {"question": "Continue with the new attempt?"}),
        Text("RECOVERED_AFTER_CALLBACK_FAILURE"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=30,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            observed_events = []
            input_requests = []

            def fail_answer(params):
                input_requests.append(dict(params))
                raise LookupError("fixture input callback failed")

            with pytest.raises(LookupError, match="fixture input callback failed"):
                server.prompt(
                    session.session_id, "retry then wait for user input",
                    on_event=observed_events.append, answer=fail_answer,
                )

            assert len(input_requests) == 1
            assert any(event.get("type") == "cancelled" for event in observed_events), [
                event.get("type") for event in observed_events
            ]
            recovered = server.prompt(
                session.session_id, "prove the previous run drained",
                on_event=observed_events.append,
            )
            assert recovered.status == "completed"
            assert "RECOVERED_AFTER_CALLBACK_FAILURE" in recovered.text

            from hermes_state import SessionDB

            with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
                transcript = db.get_messages_as_conversation(session.conversation_id)
                audit = db.list_session_events(session.conversation_id, after_seq=0, limit=1000)
            transcript_text = "\n".join(str(row.get("content") or "") for row in transcript)
            assert "OLD answer before input wait" not in transcript_text
            assert "RECOVERED_AFTER_CALLBACK_FAILURE" in transcript_text
            discarded = [
                row for row in audit
                if row.get("event_type") == "model/attempt"
                and row.get("payload", {}).get("status") == "discarded"
            ]
            assert len(discarded) == 1
            assert str(discarded[0]["payload"].get("partial_text") or "") == "OLD answer"
            assert len(fake.main_requests()) == 3
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0


@pytest.mark.parametrize("kind", ["input", "approval"])
def test_app_server_invalidates_old_pending_request_after_process_restart(tmp_path, kind):
    if kind == "input":
        scripted = [ToolCall("ask_user", {"question": "Old input?"})]
    else:
        scripted = [ToolCall("request_permissions", {
            "permission": "workspace.write", "reason": "old approval",
        })]
    with FakeLLMServer(scripted) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        first_process = first._process
        second = None
        second_process = None
        try:
            session = first.new_session()
            first.enqueue(session.session_id, "enqueue and interrupt", request_id=f"restart-{kind}")
            request = _wait_for_app_server_pending_request(first, session.session_id, fake)[0]
            first_process = first._process
            assert first_process is not None and first_process.poll() is None
            first_process.kill()  # Test-owned process crash leaves an unresolved request.
            first_process.wait(timeout=5)
            first.close()

            second = AppServer(
                [sys.executable, "-m", "atlas.cli"], workspace=workspace,
                env=isolated_env, request_timeout=60,
            ).start()
            second_process = second._process
            reopened = second.new_session(conversation_id=session.conversation_id)
            assert second.task_status(
                reopened.session_id, f"restart-{kind}",
            ).status == "outcome_unknown"
            old = next(item for item in second.pending_requests(reopened.session_id)
                       if item.request_id == request.request_id)
            assert old.status == "invalidated"
            if kind == "input":
                with pytest.raises(AppServerError, match="no longer pending"):
                    second.respond_input(request.request_id, "stale answer")
            else:
                with pytest.raises(AppServerError, match="no longer pending"):
                    second.respond_approval(request.request_id, "allow")
            audit = [item.payload for item in second.session_events(
                reopened.session_id, limit=100,
            ).events if item.event_type == "appserver.request"]
            assert any(row.get("request_id") == request.request_id
                       and row.get("state") == "invalidated" for row in audit)
            assert all(not ({"prompt", "options", "tool_args", "arguments"} & set(row))
                       for row in audit)
            assert len(fake.main_requests()) == 1
        finally:
            first.close()
            if second is not None:
                second.close()
            if second_process is not None:
                assert second_process.wait(timeout=0) == 0


def test_sdk_app_server_recovery_classifies_inflight_retry_after_process_restart(tmp_path):
    with FakeLLMServer([
        DropMidStream("OLD answer", after_chars=3),
        Hang(seconds=30),
        Text("must not replay"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="1",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="30",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        first_process = first._process
        prompt_errors = []
        prompt_thread = None
        second = None
        second_process = None
        try:
            session = first.new_session()

            def run_prompt():
                try:
                    first.prompt(session.session_id, "interrupted during retry")
                except BaseException as exc:
                    prompt_errors.append(exc)

            prompt_thread = threading.Thread(target=run_prompt, name="retry-crash-prompt")
            prompt_thread.start()
            fake.wait_for_requests(2, timeout=30)
            assert first_process is not None and first_process.poll() is None
            first_process.kill()  # Simulated crash of this test-owned app-server process.
            first_process.wait(timeout=5)
            first.close()
            prompt_thread.join(timeout=5)
            assert not prompt_thread.is_alive()
            assert prompt_errors

            second = AppServer(
                [sys.executable, "-m", "atlas.cli"], workspace=workspace,
                env=isolated_env, request_timeout=60,
            ).start()
            second_process = second._process
            reopened = second.new_session(conversation_id=session.conversation_id)
            recovery = second.retry_recovery(reopened.session_id)
            assert recovery.state == "outcome_unknown"
            assert recovery.attempt == 2
            assert recovery.retry_budget_attempts_remaining == 1
            assert recovery.recommended_action == "do_not_replay"
            assert len(fake.main_requests()) == 2
        finally:
            if prompt_thread is not None and prompt_thread.is_alive():
                if first_process is not None and first_process.poll() is None:
                    first_process.kill()
                    first_process.wait(timeout=5)
                prompt_thread.join(timeout=5)
            first.close()
            if second is not None:
                second.close()
            if second_process is not None:
                assert second_process.wait(timeout=0) == 0


def test_app_server_cancelled_retry_is_unknown_through_sdk_without_replay(tmp_path):
    with FakeLLMServer([
        DropMidStream("OLD answer", after_chars=3),
        Hang(seconds=2),
        Text("must not replay"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        isolated_env.update(
            HERMES_STREAM_RETRIES="1",
            ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS="2",
            ATLAS_MODEL_RETRY_BUDGET_SECONDS="30",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            receipt = server.enqueue(
                session.session_id, "cancel second request", request_id="cancel-retry-unknown",
            )
            fake.wait_for_requests(2, timeout=15)

            cancelled = server.cancel_task(session.session_id, receipt.request_id)
            assert cancelled.status == "cancelled"
            recovery = server.retry_recovery(session.session_id)
            assert recovery.state == "outcome_unknown"
            assert recovery.recommended_action == "do_not_replay"
            assert recovery.attempt == 2
            assert recovery.attempt_id
            assert server.task_status(
                session.session_id, receipt.request_id,
            ).status == "cancelled"
            assert len(fake.main_requests()) == 2
            server.wait(session.session_id)
            assert process is not None and process.poll() is None
            server.close_session(session.session_id)
            assert process is not None and process.stdin is not None
            process.stdin.close()
            try:
                exit_code = process.wait(timeout=12)
            except subprocess.TimeoutExpired as exc:
                raise AssertionError(
                    "app-server did not naturally exit after stdin EOF; stderr tail:\n"
                    + "\n".join(list(server._stderr_tail)[-50:])
                ) from exc
            assert exit_code == 0
            assert len(fake.main_requests()) == 2, "cancelled attempt triggered a later provider replay"
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0, "\n".join(list(server._stderr_tail)[-24:])


def test_sdk_app_server_working_directory_is_scoped_and_persisted(tmp_path):
    with FakeLLMServer([
        ToolCall("ask_user", {
            "question": "Hold this run for the cwd update check.", "options": ["Continue"],
        }),
        Text("INPUT_RESUMED"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        selected = workspace / "nested" / "selected"
        selected.mkdir(parents=True)
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        first_process = server._process
        try:
            session = server.new_session()
            server.set_working_directory(session.session_id, selected)
            assert server.get_working_directory(session.session_id) == str(selected.resolve())
            with pytest.raises(AppServerError):
                server.set_working_directory(session.session_id, tmp_path)
            with pytest.raises(AppServerError):
                server.new_session(workspace=tmp_path, conversation_id=session.conversation_id)

            receipt = server.enqueue(
                session.session_id, "pause while cwd is set", request_id="cwd-busy-check",
            )
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert pending and pending[0].kind == "input"
            with pytest.raises(AppServerError):
                server.set_working_directory(session.session_id, selected.parent)
            server.respond_input(pending[0].request_id, "continue")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, receipt.request_id).status == "completed"
        finally:
            server.close()
        assert first_process is not None
        assert first_process.wait(timeout=0) == 0

        resumed = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        resumed_process = resumed._process
        try:
            reopened = resumed.new_session(conversation_id=session.conversation_id)
            assert resumed.get_working_directory(reopened.session_id) == str(selected.resolve())
        finally:
            resumed.close()
        assert resumed_process is not None
        assert resumed_process.wait(timeout=0) == 0

        assert len(fake.main_requests()) == 2


def test_sdk_app_server_working_directory_reaches_real_local_exec(tmp_path):
    with FakeLLMServer([
        ToolCall("working_directory", {"cd": "nested/selected"}),
        ToolCall("request_permissions", {
            "permission": "workspace.write", "reason": "Run the isolated cwd marker command.",
        }),
        ToolCall("local_exec", {
            "executable": sys.executable,
            "args": ["-c", "from pathlib import Path; Path('cwd-marker.txt').write_text('cwd-ok')"],
        }),
        Text("CWD_MARKER_COMPLETED"),
        ToolCall("request_permissions", {
            "permission": "workspace.write", "reason": "Run the second isolated cwd marker command.",
        }),
        ToolCall("local_exec", {
            "executable": sys.executable,
            "args": ["-c", "from pathlib import Path; Path('cwd-marker-next-run.txt').write_text('cwd-next-run-ok')"],
        }),
        Text("CWD_NEXT_RUN_COMPLETED"),
    ]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        selected = workspace / "nested" / "selected"
        selected.mkdir(parents=True)
        server = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        process = server._process
        try:
            session = server.new_session()
            receipt = server.enqueue(
                session.session_id, "cd into nested/selected and write the cwd marker",
                request_id="cwd-real-exec",
            )
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1 and pending[0].kind == "approval"
            assert pending[0].tool_name == "working_directory"
            server.respond_approval(pending[0].request_id, "allow")
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1 and pending[0].kind == "approval"
            assert pending[0].tool_name == "request_permissions"
            server.respond_approval(pending[0].request_id, "allow")
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1 and pending[0].kind == "approval"
            assert pending[0].tool_name == "local_exec"
            assert server.get_working_directory(session.session_id) == str(selected.resolve())
            server.respond_approval(pending[0].request_id, "allow")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, receipt.request_id).status == "completed"
            assert (selected / "cwd-marker.txt").read_text(encoding="utf-8") == "cwd-ok"
            assert not (workspace / "cwd-marker.txt").exists()

            second = server.enqueue(
                session.session_id, "write the next cwd marker",
                request_id="cwd-next-run",
            )
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1 and pending[0].kind == "approval"
            assert pending[0].tool_name == "request_permissions"
            server.respond_approval(pending[0].request_id, "allow")
            pending = _wait_for_app_server_pending_request(server, session.session_id, fake)
            assert len(pending) == 1 and pending[0].kind == "approval"
            assert pending[0].tool_name == "local_exec"
            server.respond_approval(pending[0].request_id, "allow")
            server.wait(session.session_id)
            assert server.task_status(session.session_id, second.request_id).status == "completed"
            assert (selected / "cwd-marker-next-run.txt").read_text(encoding="utf-8") == "cwd-next-run-ok"
            assert server.get_working_directory(session.session_id) == str(selected.resolve())
        finally:
            server.close()
        assert process is not None and process.wait(timeout=0) == 0
        resumed = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        resumed_process = resumed._process
        try:
            reopened = resumed.new_session(conversation_id=session.conversation_id)
            assert resumed.get_working_directory(reopened.session_id) == str(selected.resolve())
        finally:
            resumed.close()
        assert resumed_process is not None and resumed_process.wait(timeout=0) == 0
        resumed_requests = fake.main_requests()
        latest_user = next(
            item for item in reversed(resumed_requests[-1].get("messages", []))
            if item.get("role") == "user"
        )
        assert "Current working directory:" in str(latest_user.get("content") or "")
        assert json.dumps(str(selected.resolve()), ensure_ascii=False) in str(
            latest_user.get("content") or "",
        )


def test_two_app_server_processes_deduplicate_same_session_enqueue_and_worker(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from atlas.engine.session_sync import read_session_events

    with FakeLLMServer([Text("ONLY_ONE_DURABLE_WORKER")]) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        second = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        processes = [first._process, second._process]
        sessions = []
        try:
            first_session = first.new_session()
            second_session = second.new_session(conversation_id=first_session.conversation_id)
            sessions = [(first, first_session), (second, second_session)]
            assert first_session.conversation_id == second_session.conversation_id

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    receipts = list(executor.map(
                        lambda pair: pair[0].enqueue(
                            pair[1].session_id, "run this durable prompt once",
                            request_id="dual-appserver-same-request",
                        ),
                        sessions,
                    ))
            except Exception as exc:
                stderr_tails = [
                    "\n".join(list(server._stderr_tail)[-20:]) for server, _ in sessions
                ]
                diagnostic_events = read_session_events(
                    tmp_path / "atlas" / "engine", first_session.conversation_id,
                    after_seq=0, limit=1000,
                )
                event_summary = [
                    (event.get("event_type"),
                     (event.get("payload") or {}).get("state"),
                     (event.get("payload") or {}).get("request_id"))
                    for event in diagnostic_events
                    if (event.get("payload") or {}).get("request_id")
                    == "dual-appserver-same-request"
                ]
                raise AssertionError(
                    f"concurrent enqueue failed: {type(exc).__name__}: {exc}; "
                    f"events={event_summary!r}; stderr={stderr_tails!r}"
                ) from exc

            assert receipts[0].event_id == receipts[1].event_id
            assert receipts[0].request_id == receipts[1].request_id
            assert receipts[0].conversation_id == receipts[1].conversation_id
            for server, session in sessions:
                server.wait(session.session_id)

            try:
                fake.wait_for_requests(1, timeout=10)
            except AssertionError as exc:
                rows = read_session_events(
                    tmp_path / "atlas" / "engine", first_session.conversation_id,
                    after_seq=0, limit=1000,
                )
                event_types = [event.get("event_type") for event in rows]
                task_states = []
                for server, session in sessions:
                    try:
                        task_states.append(server.task_status(
                            session.session_id, receipts[0].request_id,
                        ).status)
                    except Exception as status_exc:
                        task_states.append(type(status_exc).__name__)
                request_kinds = [
                    (request.get("kind"), request.get("path"), request.get("response"))
                    for request in fake.requests
                ]
                stderr_tails = [
                    "\n".join(list(server._stderr_tail)[-15:]) for server, _ in sessions
                ]
                raise AssertionError(
                    f"requests={request_kinds!r}; events={event_types!r}; "
                    f"task_states={task_states!r}; stderr={stderr_tails!r}"
                ) from exc
            assert len(fake.main_requests()) == 1
            rows = read_session_events(
                tmp_path / "atlas" / "engine", first_session.conversation_id,
                after_seq=0, limit=1000,
            )
            request_events = [
                event for event in rows
                if (event.get("payload") or {}).get("request_id")
                == "dual-appserver-same-request"
                and event.get("event_type") in {
                    "inbox.enqueued", "inbox.started", "inbox.consumed",
                }
            ]
            assert [event["event_type"] for event in request_events] == [
                "inbox.enqueued", "inbox.started", "inbox.consumed",
            ]
            assert request_events[1]["payload"]["run_id"]
            assert request_events[2]["payload"]["event_id"] == receipts[0].event_id

            for server, session in sessions:
                server.close_session(session.session_id)
            for process in processes:
                assert process is not None and process.poll() is None
                assert process.stdin is not None
                process.stdin.close()
            for process in processes:
                assert process is not None
                assert process.wait(timeout=15) == 0
            assert len(fake.main_requests()) == 1
        finally:
            first.close()
            second.close()


@pytest.mark.unit
def test_two_app_server_processes_drain_distinct_same_session_requests_in_fifo_order(tmp_path):
    from atlas.engine.session_sync import read_session_events

    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    def responder(record):
        messages = record["body"].get("messages") or []
        last_user = next((row.get("content") for row in reversed(messages)
                          if row.get("role") == "user"), "")
        value = str(last_user)
        if "CROSS_PROCESS_FIFO_FIRST" in value:
            first_started.set()
            if not release_first.wait(timeout=15):
                return Error(status=503, message="first request gate expired")
            return Text("CROSS_PROCESS_FIFO_FIRST_DONE")
        if "CROSS_PROCESS_FIFO_SECOND" in value:
            second_started.set()
            return Text("CROSS_PROCESS_FIFO_SECOND_DONE")
        return Error(status=400, message="unexpected cross-process FIFO request")

    with FakeLLMServer(responder) as fake:
        isolated_env = _isolated_app_server_env(tmp_path, fake)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        second = AppServer(
            [sys.executable, "-m", "atlas.cli"], workspace=workspace,
            env=isolated_env, request_timeout=60,
        ).start()
        processes = [first._process, second._process]
        sessions = []
        try:
            first_session = first.new_session()
            second_session = second.new_session(conversation_id=first_session.conversation_id)
            sessions = [(first, first_session), (second, second_session)]

            first_receipt = first.enqueue(
                first_session.session_id, "CROSS_PROCESS_FIFO_FIRST", request_id="fifo-first",
            )
            assert first_started.wait(timeout=15), "first request did not reach the held provider gate"
            second_receipt = second.enqueue(
                second_session.session_id, "CROSS_PROCESS_FIFO_SECOND", request_id="fifo-second",
            )
            assert second_receipt.event_id != first_receipt.event_id
            assert second.task_status(second_session.session_id, "fifo-second").status == "queued"
            assert not second_started.wait(timeout=0.5), "second app-server bypassed the active FIFO head"

            release_first.set()
            first.wait(first_session.session_id)
            try:
                fake.wait_for_requests(2, timeout=5)
            except AssertionError as exc:
                diagnostic_events = read_session_events(
                    tmp_path / "atlas" / "engine", first_session.conversation_id,
                    after_seq=0, limit=1000,
                )
                lifecycle = [
                    (row.get("event_type"), (row.get("payload") or {}).get("request_id"))
                    for row in diagnostic_events
                    if (row.get("payload") or {}).get("request_id") in {"fifo-first", "fifo-second"}
                ]
                statuses = [
                    server.task_status(session.session_id, request_id).status
                    for (server, session), request_id in zip(sessions, ("fifo-first", "fifo-second"))
                ]
                raise AssertionError(
                    f"second queued request did not run after FIFO head; statuses={statuses!r}; "
                    f"lifecycle={lifecycle!r}; provider_requests={len(fake.main_requests())}"
                ) from exc

            second.wait(second_session.session_id)
            assert second_started.is_set()
            assert first.task_status(first_session.session_id, "fifo-first").status == "completed"
            assert second.task_status(second_session.session_id, "fifo-second").status == "completed"
            requests = fake.main_requests()
            prompts = [next((str(row.get("content") or "") for row in reversed(request["messages"])
                             if row.get("role") == "user"), "") for request in requests]
            observed_order = [next(marker for marker in (
                "CROSS_PROCESS_FIFO_FIRST", "CROSS_PROCESS_FIFO_SECOND",
            ) if marker in prompt) for prompt in prompts]
            assert observed_order == ["CROSS_PROCESS_FIFO_FIRST", "CROSS_PROCESS_FIFO_SECOND"]
            assert len(requests) == 2

            rows = read_session_events(
                tmp_path / "atlas" / "engine", first_session.conversation_id,
                after_seq=0, limit=1000,
            )
            lifecycle = [
                row for row in rows
                if (row.get("payload") or {}).get("request_id") in {"fifo-first", "fifo-second"}
                and row.get("event_type") in {"inbox.enqueued", "inbox.started", "inbox.consumed"}
            ]
            by_request = {
                request_id: [row for row in lifecycle
                             if (row.get("payload") or {}).get("request_id") == request_id]
                for request_id in ("fifo-first", "fifo-second")
            }
            assert {key: [row["event_type"] for row in value] for key, value in by_request.items()} == {
                "fifo-first": ["inbox.enqueued", "inbox.started", "inbox.consumed"],
                "fifo-second": ["inbox.enqueued", "inbox.started", "inbox.consumed"],
            }
            seq = {request_id: {
                row["event_type"]: int(row["seq"]) for row in value
            } for request_id, value in by_request.items()}
            assert seq["fifo-first"]["inbox.started"] < seq["fifo-second"]["inbox.enqueued"]
            assert seq["fifo-second"]["inbox.enqueued"] < seq["fifo-first"]["inbox.consumed"]
            assert seq["fifo-first"]["inbox.consumed"] < seq["fifo-second"]["inbox.started"]

            for server, session in sessions:
                server.close_session(session.session_id)
            for process in processes:
                assert process is not None and process.poll() is None
                assert process.stdin is not None
                process.stdin.close()
            for process in processes:
                assert process is not None
                assert process.wait(timeout=15) == 0
        finally:
            release_first.set()
            first.close()
            second.close()
