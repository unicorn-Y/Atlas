import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.memory.library import MemoryLibrary
from atlas.memory.library import extract
from atlas.memory.library.store import Entry, ME, NOW, Page, SRC_SAID


class FakeRouter:
    def __init__(self, responses):
        self.responses = list(responses)

    async def complete_for(self, *_args, **_kwargs):
        return SimpleNamespace(text=json.dumps(self.responses.pop(0), ensure_ascii=False))


class FakeModelManager:
    current_model = "fake-model"

    def __init__(self, responses):
        self.model_router = FakeRouter(responses)

    def list_models(self):
        return [{"id": "fake-model"}]


def fact(key, value, text, quote):
    return {"facts": [{"op": "set", "key": key, "value": value,
                       "text": text, "quote": quote, "triggers": [], "importance": 5}]}


def add_fact(lib, *, key, value, text, quote, now=None):
    lib.ready()
    now = now or datetime.now().astimezone()
    result = lib._apply([extract.Proposal(op="set", key=key, value=value, text=text,
                                          quote=quote)], quote, "test", "expert", now)
    return result


def test_m01_edited_keyed_value_is_replaced_and_old_text_moves_to_history(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    add_fact(lib, key="user.home_city", value="杭州", text="住在杭州", quote="我住杭州")
    entry = lib.store.read(ME).current[0]
    lib.edit_entry(entry.id, "住在北京")

    async def write_turn():
        model_mgr = FakeModelManager([fact("user.home_city", "杭州", "住在杭州", "我住杭州")])
        lib.schedule_turn(user_text="我住杭州", assistant_text="好的", session="s1",
                          mode="expert", model_mgr=model_mgr)
        await lib._drain(model_mgr)

    asyncio.run(write_turn())

    page = lib.store.read(ME)
    assert [(e.text, e.value) for e in page.current] == [("住在杭州", "杭州")]
    assert any(e.text == "住在北京" for e in page.history)


def test_m02_forget_removes_text_from_pages_index_diary_and_git_history(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    result = lib.add_entry(ME, "极光密钥城市杭州")
    for i in range(3):
        page = lib.store.read(ME)
        page.notes.append(f"unrelated-{i}")
        lib.store.write(page)
        lib.store.commit(f"unrelated-{i}")

    report = lib.forget_entry(result["id"])

    assert report["history"]["rewritten"] is True
    assert not list(tmp_path.glob(".git-before-forget-*"))
    assert all("极光密钥城市杭州" not in (tmp_path / p).read_text(encoding="utf-8")
               for p in lib.store.pages() + lib.store.diary_pages())
    assert "极光密钥城市杭州" not in json.dumps(lib.search("极光密钥城市杭州", include_history=True),
                                                ensure_ascii=False)
    assert "极光密钥城市杭州" not in json.dumps(lib.changes(), ensure_ascii=False)
    assert "极光密钥城市杭州" not in lib.store._git("log", "--all", "-p")
    assert "极光密钥城市杭州" not in lib.store._git("log", "--all", "--format=%B")


def test_m02b_revert_cannot_restore_a_forgotten_entry(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    result = lib.add_entry(ME, "隐去文本的星尘地名")
    remembered_sha = lib.store.log(1)[0]["sha"]
    lib.forget_entry(result["id"])
    sha = lib.store.log(100)[0]["sha"]

    with pytest.raises(ValueError):
        lib.revert(remembered_sha)
    with pytest.raises(ValueError):
        lib.revert(sha)
    assert "隐去文本的星尘地名" not in (tmp_path / ME).read_text(encoding="utf-8")


def test_m03_pending_turn_survives_library_restart(tmp_path, monkeypatch):
    lib = MemoryLibrary(tmp_path)
    model_mgr = FakeModelManager([fact("user.home_city", "杭州", "住在杭州", "我住在杭州")])
    scheduled = []

    class DeferredTask:
        def __init__(self, coro):
            self.coro = coro

        def add_done_callback(self, _callback):
            pass

    monkeypatch.setattr(asyncio, "create_task", lambda coro: scheduled.append(DeferredTask(coro)) or scheduled[-1])
    lib.schedule_turn(user_text="我住在杭州", assistant_text="记下了", session="s2",
                      mode="expert", model_mgr=model_mgr)

    restarted = MemoryLibrary(tmp_path)
    asyncio.run(restarted._drain(model_mgr))

    assert len(restarted.store.diary_pages()) == 1
    assert restarted.store.read(ME).current[0].text == "住在杭州"
    assert restarted.queue.count() == 0
    for task in scheduled:
        task.coro.close()


def test_m04_expired_entry_is_hidden_until_history_search(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).isoformat(timespec="seconds")
    page = lib.store.read(NOW)
    page.current.append(Entry(text="火星基地的短期任务", key="project.mars.status",
                              value="进行中", until=yesterday, src=SRC_SAID))
    lib.store.write(page)
    lib.store.commit("expired setup")

    recalled = lib.recall("火星基地任务")
    assert "火星基地的短期任务" not in recalled["resident"]
    assert "火星基地的短期任务" not in json.dumps(lib.search("火星基地任务"), ensure_ascii=False)
    history = lib.search("火星基地任务", include_history=True)
    assert any(hit["text"] == "火星基地的短期任务" and hit["expired"] for hit in history)


def test_m05_resident_budget_keeps_a_floor_for_each_page(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    me = lib.store.read(ME)
    me.current = [Entry(text=f"本人长事实{i}-" + "甲" * 90, at=f"2026-01-{i % 28 + 1:02d}")
                  for i in range(30)]
    lib.store.write(me)
    now = lib.store.read(NOW)
    now.current = [Entry(text="现状页必须保留的关键事项", at="2026-01-01")]
    lib.store.write(now)

    resident = lib.recall("无关查询词")["resident"]
    assert "现状页必须保留的关键事项" in resident


def test_m06_filtering_resident_hits_happens_before_search_limit(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    me = lib.store.read(ME)
    me.current = [Entry(text=f"琥珀象限共同词本人记录{i}", key=f"user.fact{i}", value="琥珀象限")
                  for i in range(15)]
    lib.store.write(me)
    person = Page(path="人/林.md", title="林")
    person.current = [Entry(text="琥珀象限共同词林的项目", key="person.林.project", value="琥珀象限")]
    lib.store.write(person)
    lib.index.sync()

    relevant, _ = lib._relevant_block("琥珀象限共同词")
    assert "琥珀象限共同词林的项目" in relevant


def test_m07_hypothetical_proposal_is_rejected(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    response = fact("user.home_city", "北京", "住在北京", "假如我住北京")
    response["facts"][0]["stance"] = "hypothetical"

    async def apply_response():
        model_mgr = FakeModelManager([response])
        now = datetime.now().astimezone()
        proposals = await lib._extract("假如我住北京会怎样", "", model_mgr, now)
        return lib._apply(proposals, "假如我住北京会怎样", "s3", "expert", now)

    result = asyncio.run(apply_response())

    assert not any(e.text == "住在北京" for rel in lib.store.pages()
                   for e in lib.store.read(rel).current)
    assert result.rejected == 1


def test_m09_empty_memory_has_no_relevant_section(tmp_path):
    lib = MemoryLibrary(tmp_path)

    assert lib.recall("我上次说的那家店叫什么")["relevant"] == ""
