"""Exercise one end-to-end local scenario for each U32 implementation."""

from __future__ import annotations

import asyncio
import gc
import tempfile
from pathlib import Path

from atlas.channels.contract import MessageEvent
from atlas.channels.routing import resolve_route
from atlas.sharing import ConversationShareStore, shared_page_html
from atlas.workflow.journal import WorkflowJournal
from atlas.workflow.scheduler import run_workflow
from atlas.workflow.types import NodeResult, WorkflowGraph, WorkflowNode


def check_group_routing() -> None:
    event = MessageEvent(
        channel="telegram", account="work", event_id="evt-1", chat_id="ops-room",
        sender_id="human", is_group=True, mentions=["review"],
    )
    bindings = [
        {"agent_id": "general", "channel": "telegram", "account": "*", "peer_kind": "group"},
        {"agent_id": "reviewer", "channel": "telegram", "account": "work", "peer_id": "ops-room",
         "mention_names": ["review"]},
    ]
    assert resolve_route(bindings, event) == "reviewer"


def check_workflow_stop(root: Path) -> None:
    journal = WorkflowJournal(root / "workflow.db")
    graph = WorkflowGraph("U32 stop scenario", [WorkflowNode("wait", "wait for cancellation")],
                          str(root), workflow_id="u32-live-stop")
    journal.ensure_graph(graph)
    journal.bind_context(graph.workflow_id, "u32-conversation")
    assert journal.current_for_conversation("u32-conversation")["workflow_id"] == graph.workflow_id

    class WaitingRunner:
        async def run(self, **_kwargs):
            await asyncio.Event().wait()
            return NodeResult("unreachable")

    async def stop_on_start(event: dict) -> None:
        if event["type"] == "node_started":
            await asyncio.to_thread(journal.request_cancel, graph.workflow_id)

    result = asyncio.run(run_workflow(graph, WaitingRunner(), max_parallel=1,
                                      on_event=stop_on_start, journal=journal))
    assert result.status == "cancelled" and journal.status(graph.workflow_id) == "cancelled"


def check_focus_preferences() -> None:
    app = Path(__file__).resolve().parents[2] / "frontend" / "src" / "renderer" / "App.tsx"
    thread = app.parent / "components" / "MessageThread.tsx"
    shortcuts = app.parent / "services" / "shortcuts.ts"
    app_text, thread_text, shortcut_text = app.read_text(encoding="utf-8"), thread.read_text(encoding="utf-8"), shortcuts.read_text(encoding="utf-8")
    assert "pref('focus-mode')" in app_text and "setPref('focus-mode'" in app_text and "/focus" in app_text
    assert "focusMode" in thread_text and "Ctrl+Shift+O" in shortcut_text


def check_share_round_trip(root: Path) -> None:
    store = ConversationShareStore(root / "shares.db")
    created = store.create(
        conversation_id="source-conversation", title="U32 share scenario",
        base_url="https://share.example/atlas", password="local-pass", retention_days=1,
        messages=[{"role": "user", "content": "import this"},
                  {"role": "assistant", "content": "read-only snapshot"}],
    )
    token = created["url"].rsplit("/", 1)[-1]
    assert store.read(token, allow_locked=True)["password_protected"]
    assert store.read(token, "local-pass")["messages"][1]["content"] == "read-only snapshot"
    page = shared_page_html(created["url"], {**store.read(token, "local-pass"), "token": token})
    assert "atlas://share/" + token in page and "import this" in page
    assert store.revoke(created["id"]) and store.read(token, "local-pass") is None


def main() -> None:
    check_group_routing()
    with tempfile.TemporaryDirectory(prefix="atlas-u32-") as temporary:
        root = Path(temporary)
        check_workflow_stop(root)
        check_share_round_trip(root)
        gc.collect()  # Drop Windows SQLite handle cycles before TemporaryDirectory cleanup.
    check_focus_preferences()
    print("1/4 group mention routing: PASS")
    print("2/4 expert workflow stop: PASS")
    print("3/4 conversation focus wiring: PASS")
    print("4/4 hosted share and import link: PASS")
    print("U32 CHECK PASS")


if __name__ == "__main__":
    main()
