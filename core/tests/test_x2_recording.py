"""X2 learned browser workflow tests — fake browser only, no network, no model.

Covers: capture of model-driven actions (site / page-structure fingerprint /
@eN ref / action / params), replay with model-invoke counter == 0, forced step
failure → exactly ONE single-step self-heal replan → step record updated and
persisted, the to-skill bundle shape, and store round-trip under the isolated
Atlas data dir.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from atlas.tools.x2 import browser as x2browser
from atlas.tools.x2 import recording as rec
from atlas.tools.x2.context import X2Context, reset_context, set_context
from atlas.tools.x2.recording import (
    Recorder,
    RecordingStore,
    ReplayEngine,
    model_replanner,
    new_recording_id,
    origin_of,
    parse_snapshot,
    save_skill,
    to_skill_bundle,
)

SNAPSHOT = "\n".join([
    '- heading "购物车" [ref=e1]',
    '- textbox "搜索" [ref=e2]',
    '- button "结算" [ref=e3]',
])


class FakeReplayBrowser:
    """ReplayEngine browser adapter; scripted failures popped in order."""

    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []
        self.failures: dict[int, list[str]] = {}  # step index -> queued errors

    async def execute(self, step: dict[str, Any]) -> dict[str, Any]:
        self.executed.append(dict(step))
        queue = self.failures.get(parse_index(step))
        if queue:
            error = queue.pop(0)
            return {"ok": False, "error": error,
                    "snapshot": SNAPSHOT, "url": "https://shop.example.com/cart"}
        return {"ok": True, "url": "https://shop.example.com/cart", "snapshot": SNAPSHOT}


def make_ctx() -> X2Context:
    return X2Context(run_id="run-1", session_id="sess-1", emit=None, wait_input=None)


def parse_index(step: dict[str, Any]) -> int:
    return int(step.get("index", -1))


# ---------------------------------------------------------------------------
# Capture (through the runtime bridge, as the model drives the browser tool)
# ---------------------------------------------------------------------------
class FakeBrowser:
    async def call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "navigate":
            return {"success": True, "url": params.get("url", ""), "title": "购物车",
                    "snapshot": SNAPSHOT, "element_count": 3}
        if action == "snapshot":
            return {"success": True, "snapshot": SNAPSHOT, "element_count": 3}
        if action == "click":
            return {"success": True, "clicked": params.get("ref", "")}
        if action == "type":
            return {"success": True, "typed": "•••", "element": params.get("ref", "")}
        return {"success": True}


async def test_capture_records_site_fingerprint_ref_action_params(tmp_path) -> None:
    rt = x2browser.X2BrowserRuntime(backend=FakeBrowser(), store=RecordingStore(tmp_path / "recs"))
    x2browser.set_runtime(rt)
    token = set_context(make_ctx())
    try:
        doc = rt.start_recording()
        await rt.call_tool("browser_navigate", {"url": "https://shop.example.com/cart"})
        await rt.call_tool("browser_type", {"ref": "e2", "text": "机械键盘"})
        await rt.call_tool("browser_click", {"ref": "@e3"})
        stopped = rt.stop_recording()
    finally:
        reset_context(token)

    assert stopped["recording_id"] == doc["recording_id"]
    assert stopped["site"] == "https://shop.example.com"
    steps = stopped["steps"]
    assert [s["action"] for s in steps] == ["navigate", "type", "click"]
    fingerprint, elements = parse_snapshot(SNAPSHOT)
    assert fingerprint and len(elements) == 3
    for step in steps:
        assert step["site"] == "https://shop.example.com"
        assert step["fingerprint"] == fingerprint  # same page → same structure hash
    typing, click = steps[1], steps[2]
    assert typing["ref"] == "@e2" and typing["params"]["ref"] == "@e2"
    assert typing["element"] == 'textbox "搜索"'  # ref resolved against the a11y snapshot
    assert typing["params"]["text"] == "机械键盘"
    assert "task_id" not in typing["params"]  # session plumbing never recorded
    assert click["ref"] == "@e3" and click["element"] == 'button "结算"'
    # Persisted immediately: a fresh store sees the same steps.
    assert RecordingStore(tmp_path / "recs").load(doc["recording_id"])["steps"] == steps


async def test_failed_actions_are_not_recorded(tmp_path) -> None:
    backend = FakeBrowser()

    async def broken(action, params):
        return {"success": False, "error": "元素不存在"}

    async def call(action, params):
        if action == "click":
            return await broken(action, params)
        return await FakeBrowser.call(backend, action, params)

    backend.call = call  # type: ignore[method-assign]
    rt = x2browser.X2BrowserRuntime(backend=backend, store=RecordingStore(tmp_path / "recs"))
    x2browser.set_runtime(rt)
    token = set_context(make_ctx())
    try:
        rt.start_recording()
        await rt.call_tool("browser_navigate", {"url": "https://shop.example.com/"})
        await rt.call_tool("browser_click", {"ref": "@e99"})  # fails → not recorded
        doc = rt.stop_recording()
    finally:
        reset_context(token)
    assert [s["action"] for s in doc["steps"]] == ["navigate"]


# ---------------------------------------------------------------------------
# Replay: zero model calls on the happy path
# ---------------------------------------------------------------------------
def sample_doc(store: RecordingStore) -> dict[str, Any]:
    doc = store.create(site="https://shop.example.com")
    fingerprint, _ = parse_snapshot(SNAPSHOT)
    doc["steps"] = [
        {"index": 0, "site": doc["site"], "fingerprint": fingerprint, "ref": "",
         "element": "", "action": "navigate", "params": {"url": "https://shop.example.com/cart"},
         "description": "navigate"},
        {"index": 1, "site": doc["site"], "fingerprint": fingerprint, "ref": "@e3",
         "element": 'button "结算"', "action": "click", "params": {"ref": "@e3"},
         "description": 'click button "结算"'},
    ]
    store.save(doc)
    return doc


async def test_replay_makes_zero_model_calls(tmp_path) -> None:
    store = RecordingStore(tmp_path / "recs")
    doc = sample_doc(store)
    browser = FakeReplayBrowser()
    model_calls = 0

    async def any_model(prompt: str) -> str:
        nonlocal model_calls
        model_calls += 1
        return "{}"

    engine = ReplayEngine(browser, store, replanner=model_replanner(any_model))
    outcome = await engine.replay(doc)

    assert outcome["ok"] is True
    assert outcome["executed"] == 2 and outcome["healed"] == []
    assert model_calls == 0  # replay never touches the model
    assert [s["action"] for s in browser.executed] == ["navigate", "click"]


async def test_replay_by_id_without_replanner_fails_closed(tmp_path) -> None:
    store = RecordingStore(tmp_path / "recs")
    doc = sample_doc(store)
    browser = FakeReplayBrowser()
    browser.failures = {1: ["元素消失"]}
    engine = ReplayEngine(browser, store, replanner=None)
    outcome = await engine.replay_recording(doc["recording_id"])
    assert outcome["ok"] is False
    assert outcome["failed_index"] == 1
    assert store.load(doc["recording_id"])["steps"][1].get("healed") is None
    missing = await engine.replay_recording("rec-missing")
    assert missing["ok"] is False and "没有" in missing["error"]


# ---------------------------------------------------------------------------
# Self-heal: forced failure → one replan → step record updated + persisted
# ---------------------------------------------------------------------------
async def test_forced_failure_self_heals_exactly_one_step(tmp_path) -> None:
    store = RecordingStore(tmp_path / "recs")
    doc = sample_doc(store)
    browser = FakeReplayBrowser()
    browser.failures = {1: ["stale element: @e3 no longer exists"]}
    replan_inputs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def replan(step: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any] | None:
        replan_inputs.append((dict(step), dict(failure)))
        return {"ref": "@e7", "params": {"ref": "@e7"}, "element": 'button "去结算"'}

    engine = ReplayEngine(browser, store, replanner=replan)
    outcome = await engine.replay_recording(doc["recording_id"])

    assert outcome["ok"] is True and outcome["healed"] == [1]
    assert len(replan_inputs) == 1  # exactly ONE single-step replan
    step, failure = replan_inputs[0]
    assert step["ref"] == "@e3"
    assert "stale element" in failure["error"] and failure["snapshot"]

    persisted = store.load(doc["recording_id"])
    healed_step = persisted["steps"][1]
    assert healed_step["ref"] == "@e7" and healed_step["params"] == {"ref": "@e7"}
    assert healed_step["element"] == 'button "去结算"' and healed_step.get("healed") is True
    # The healed (updated) ref is what got re-executed.
    assert browser.executed[-1]["params"]["ref"] == "@e7"


async def test_model_replanner_parses_json_and_gives_up(tmp_path) -> None:
    async def gives_up(prompt: str) -> str:
        assert "原步骤" in prompt and "失败原因" in prompt
        return json.dumps({"give_up": True})

    assert await model_replanner(gives_up)({"index": 1}, {"error": "x"}) is None

    async def garbage(prompt: str) -> str:
        return "not json"

    assert await model_replanner(garbage)({"index": 1}, {"error": "x"}) is None

    async def heals(prompt: str) -> str:
        return json.dumps({"action": "click", "ref": "@e9", "params": {"ref": "@e9"}})

    healed = await model_replanner(heals)({"index": 1}, {"error": "x"})
    assert healed == {"action": "click", "ref": "@e9", "params": {"ref": "@e9"}}


async def test_runtime_replay_tool_reports_failure_and_success(tmp_path) -> None:
    store = RecordingStore(tmp_path / "recs")
    sample_doc(store)
    rt = x2browser.X2BrowserRuntime(backend=FakeBrowser(), store=store)
    x2browser.set_runtime(rt)
    token = set_context(make_ctx())
    try:
        missing = await rt.call_tool("browser_replay", {"recording_id": "rec-missing"})
        assert missing["is_error"] and "没有" in missing["data"]["error"]
        recording_id = store.list()[0]["recording_id"]
        ok = await rt.call_tool("browser_replay", {"recording_id": recording_id})
    finally:
        reset_context(token)
    assert not ok["is_error"]
    assert ok["data"]["executed"] == 2 and ok["data"]["healed"] == []


# ---------------------------------------------------------------------------
# to-skill bundle
# ---------------------------------------------------------------------------
def test_to_skill_bundle_shape(tmp_path) -> None:
    store = RecordingStore(tmp_path / "recs")
    doc = sample_doc(store)
    bundle = to_skill_bundle(doc)

    assert {"name", "description", "skill_md", "steps"} <= set(bundle)
    assert bundle["name"] == "shop-example-com-flow"
    assert "shop.example.com" in bundle["description"] and "2 步" in bundle["description"]
    assert bundle["skill_md"].startswith("---\n")
    assert f"name: {bundle['name']}" in bundle["skill_md"]
    assert 'click button "结算"' in bundle["skill_md"]
    assert doc["recording_id"] in bundle["skill_md"]  # replay pointer
    assert bundle["steps"] == doc["steps"]

    custom = to_skill_bundle(doc, name="checkout-flow", description="一键结算")
    assert custom["name"] == "checkout-flow" and "一键结算" in custom["description"]

    path = save_skill(custom, skills_dir=tmp_path / "skills")
    assert path == tmp_path / "skills" / "checkout-flow" / "SKILL.md"
    assert path.read_text(encoding="utf-8") == custom["skill_md"]


def test_bundle_params_never_contain_secrets(tmp_path) -> None:
    doc = {"recording_id": new_recording_id(), "site": "https://a.example.com", "steps": [{
        "index": 0, "site": "https://a.example.com", "fingerprint": "x", "ref": "@e1",
        "element": "", "action": "type", "params": {"ref": "@e1", "text": "t", "password": "boom"},
        "description": "type",
    }]}
    bundle = to_skill_bundle(doc)
    blob = json.dumps(bundle, ensure_ascii=False)
    # Recorder already strips secret-shaped params; the bundle mirrors that.
    assert "boom" not in blob


# ---------------------------------------------------------------------------
# Store + helpers
# ---------------------------------------------------------------------------
def test_store_roundtrip_and_listing(tmp_path) -> None:
    store = RecordingStore(tmp_path / "recs")
    one = store.create(site="https://one.example.com")
    two = store.create(site="https://two.example.com")
    assert store.load(one["recording_id"])["site"] == "https://one.example.com"
    assert store.load("missing") is None
    summaries = store.list()
    ids = {s["recording_id"] for s in summaries}
    assert {one["recording_id"], two["recording_id"]} <= ids
    assert all("step_count" in s and "status" in s for s in summaries)
    # Path traversal cannot escape the recordings dir.
    assert store.load("../../etc/passwd") is None


def test_recorder_observe_updates_fingerprint_and_site() -> None:
    doc = {"recording_id": new_recording_id(), "site": "", "status": "recording", "steps": []}
    recorder = Recorder(doc, RecordingStore())
    recorder.observe(SNAPSHOT, "https://shop.example.com/cart?p=1")
    assert recorder.active is True
    recorder.record("click", {"ref": "e3"})
    assert doc["steps"][0]["site"] == origin_of("https://shop.example.com/cart?p=1")
    recorder.stop()
    assert recorder.active is False and doc["status"] == "stopped"


def test_recordings_dir_under_atlas_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import atlas.config as config_module

    monkeypatch.setattr(config_module, "DATA_ROOT", tmp_path, raising=False)
    directory = rec.recordings_dir()
    assert str(tmp_path) in str(directory)
    assert directory.as_posix().endswith("browser-cache/recordings")
