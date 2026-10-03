"""K1 phase G3, part 2: daily paths that cross the X2/X4/X5 surface.

Scenarios 7-11 of the K1 daily-path list, driven over the real HTTP/WS
surface with the fake model. The X2 browser/computer bridges, X4 market
router and X5 evolution router are wired into ``atlas.server`` (Phase F
integration commits), so these run for real; a scenario that still cannot
pass carries ``xfail(strict=False)`` with the precise missing seam in its
reason.
"""

from __future__ import annotations

import pytest

from tests.fakes.fake_llm_provider import Text, ToolCall
from tests.fakes.k1_harness import k1_backend  # noqa: F401  (fixture)

# The SKILLS_DIR real bug (atlas.config lacked the symbol; market routes 500'd)
# was fixed 2026-10-03 — market fallback root is now derived from db_path.parent.
# Scenarios 9/10/11 run as real tests again.


def _skill_names(listing) -> list[str]:
    items = listing if isinstance(listing, list) else listing.get("skills", [])
    return [str(item.get("name")) for item in items]


# ---------------------------------------------------------------------------
# 7. browser multi-step through the X2 browser bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_browser_multistep(k1_backend):  # noqa: F811
    backend = k1_backend
    page = backend.root / "workspace/k1-page.html"
    page.write_text("<html><body><h1>K1_BROWSER_FIXTURE</h1></body></html>", encoding="utf-8")
    steps = {"n": 0}

    def responder(record):
        steps["n"] += 1
        if steps["n"] == 1:
            return ToolCall("browser_navigate", {"url": page.as_uri()})
        if steps["n"] == 2:
            return ToolCall("browser_snapshot", {})
        return Text("K1_BROWSER_DONE")

    backend.fake._responder = responder
    _, events = await backend.run("open the local page in the browser and read its heading",
                                  timeout=240)
    # The browser actions must really execute and their results must reach the
    # model transcript (KNOWN GAP, reported: X2 tools emit no tool.started /
    # tool.completed events on /ws/chat, so activity is invisible to the UI).
    assert steps["n"] >= 3, "the browser tool plan must consume three model turns"
    transcript = str(backend.fake.main_requests()[-1])
    assert "K1_BROWSER_FIXTURE" in transcript, \
        "the browser snapshot result must carry the page heading"
    assert any(e["event"] == "message.completed"
               and "K1_BROWSER_DONE" in str(e["data"].get("content")) for e in events)
    assert events[-1]["event"] == "run.completed"


# ---------------------------------------------------------------------------
# 8. computer-use through a fake Cua driver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_computer_use_with_fake_driver(k1_backend):  # noqa: F811
    backend = k1_backend
    steps = {"n": 0}

    def responder(record):
        steps["n"] += 1
        if steps["n"] == 1:
            return ToolCall("computer_observe", {"target": "desktop"})
        return Text("K1_COMPUTER_DONE")

    backend.fake._responder = responder
    _, events = await backend.run("observe the desktop through the fake Cua driver", timeout=180)
    # The observation must really execute through the X2 bridge and complete.
    observes = [e for e in events if e["event"] == "tool.completed"
                and str(e["data"].get("name", "")).startswith("computer")]
    assert observes, [e["event"] for e in events]
    result = observes[0]["data"]
    assert not result.get("is_error"), str(result.get("result"))[:300]
    observed = str(result.get("result"))
    carries_evidence = ("_multimodal" in result or "screenshot" in observed.lower()
                        or "image" in observed.lower())
    assert carries_evidence, "the observation must carry screen evidence"
    # The evidence must be a real image payload...
    assert "data:image/png" in observed, observed[:300]
    # ...produced by the FAKE driver (never a real desktop grab).
    assert "K1_FAKE" in observed, observed[:300]
    assert any(e["event"] == "message.completed"
               and "K1_COMPUTER_DONE" in str(e["data"].get("content")) for e in events)


# ---------------------------------------------------------------------------
# 9. skills: search / install / use / update / uninstall through market endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_skills_market_install_use_update_uninstall(k1_backend):  # noqa: F811
    backend = k1_backend
    market_dir = backend.root / "market"
    skill_dir = market_dir / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\nversion: 1.0.0\ndescription: K1 fixture skill\n---\n\n"
        "K1_SKILL_INSTRUCTION do the fixture thing.\n", encoding="utf-8")

    added = await backend.http.post("/api/skills/market/sources",
                                    json={"name": "k1-local", "kind": "directory",
                                          "path": str(market_dir)})
    assert added.status_code == 200, added.text

    found = (await backend.http.get("/api/skills/market/search?q=demo")).json()
    assert found.get("count", 0) >= 1, found
    # Pin the LOCAL tap entry: hub sources may reach the live network and a
    # real ClawHub skill named "demo-skill" exists — never install that here.
    entries = [item for item in found.get("results", [])
               if item.get("id") == "demo-skill" and item.get("source") == "k1-local"]
    assert entries, f"k1-local demo-skill not in search results: {found}"
    entry = entries[0]

    installed = await backend.http.post("/api/skills/market/install",
                                        json={"source": entry["source"], "id": entry["id"]})
    assert installed.status_code == 200, installed.text
    assert installed.json()["status"] == "installed", installed.text
    listing = await backend.http.get("/api/skills")
    assert listing.status_code == 200
    assert "demo-skill" in _skill_names(listing.json()), listing.text

    # use: a run with the skill active must inject its instructions
    backend.fake._responder = lambda record: Text("K1_SKILL_USED")
    _, events = await backend.run("use the installed demo skill",
                                  active_skills=["demo-skill"])
    assert any(e["event"] == "message.completed"
               and "K1_SKILL_USED" in str(e["data"].get("content")) for e in events)
    assert any("K1_SKILL_INSTRUCTION" in str(request)
               for request in backend.fake.main_requests()), \
        "an active skill's instructions must reach the model"

    updates = (await backend.http.get("/api/skills/updates")).json()
    assert updates.get("count", 0) >= 1, updates
    updated = await backend.http.post("/api/skills/market/update", json={"name": "demo-skill"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] in {"updated", "up_to_date"}, updated.text

    enabled = await backend.http.post("/api/skills/market/demo-skill/enable")
    assert enabled.status_code == 200 and enabled.json()["status"] == "active", enabled.text

    removed = await backend.http.delete("/api/skills/demo-skill")
    assert removed.status_code == 200 and removed.json()["status"] == "removed", removed.text
    after = await backend.http.get("/api/skills")
    assert "demo-skill" not in _skill_names(after.json()), after.text


# ---------------------------------------------------------------------------
# 10. X2 recording -> skill -> replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_recording_to_skill_and_replay(k1_backend):  # noqa: F811
    backend = k1_backend
    started = await backend.http.post("/api/browser/recordings", json={"action": "start"})
    assert started.status_code == 200, started.text
    recording_id = started.json().get("recording_id")
    assert recording_id, started.text

    stopped = await backend.http.post("/api/browser/recordings", json={"action": "stop"})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json().get("recording_id") == recording_id

    detail = await backend.http.get(f"/api/browser/recordings/{recording_id}")
    assert detail.status_code == 200, detail.text
    assert "steps" in detail.json(), detail.json()

    saved = await backend.http.post(f"/api/browser/recordings/{recording_id}/to-skill",
                                    json={"save": True, "name": "k1-recorded-skill"})
    assert saved.status_code == 200 and saved.json().get("saved") is True, saved.text
    listing = await backend.http.get("/api/skills")
    assert "k1-recorded-skill" in _skill_names(listing.json()), listing.text

    # replay: the recorded skill is a real installed skill and can drive a run
    backend.fake._responder = lambda record: Text("K1_REPLAY_DONE")
    _, events = await backend.run("replay the k1-recorded-skill",
                                  active_skills=["k1-recorded-skill"])
    assert any(e["event"] == "message.completed"
               and "K1_REPLAY_DONE" in str(e["data"].get("content")) for e in events)
    assert events[-1]["event"] == "run.completed"


# ---------------------------------------------------------------------------
# 11. X5 candidate -> approve -> install
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_x5_candidate_approve_install(k1_backend):  # noqa: F811
    backend = k1_backend
    created = await backend.http.post("/api/evolution/candidates", json={
        "name": "k1-evolved-skill", "description": "K1 evolved fixture skill",
        "origin": "user_request", "parameters": {"steps": ["do the evolved thing"]}})
    assert created.status_code == 200 and created.json()["ok"] is True, created.text
    candidate = created.json()["candidate"]
    candidate_id = candidate["id"]

    listed = (await backend.http.get("/api/evolution/candidates")).json()
    assert any(item["id"] == candidate_id for item in listed["candidates"]), listed

    approved = await backend.http.post(f"/api/evolution/candidates/{candidate_id}/approve")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body.get("ok") is True and body.get("saved") is True, approved.text
    assert body.get("skill") == "k1-evolved-skill", approved.text

    listing = await backend.http.get("/api/skills")
    assert "k1-evolved-skill" in _skill_names(listing.json()), listing.text
