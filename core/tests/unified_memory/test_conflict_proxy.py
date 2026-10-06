"""T03.3 Atlas-side integration: conflicts + corrections via /api/unified-memory proxy.

T01.3 的代理面是**表驱动透传**（core/atlas/api/unified_memory_router.py
``PROXY_ROUTES`` 已含 POST /recall、POST /observe、POST /corrections、
GET /records/{record_ref}），请求体原样转发（facade.call 不改写 body），
MemoryOS 侧 T03.3 接线后代理自动跟随 —— 本文件验证：

  * seed conflict（经代理 observe 落两条同 key 传闻冲突）→ 代理 recall 拿到
    conflicts：``conflicts[0]["kind"] == "UNRESOLVED"`` 且顶层/冲突内
    ``missing_evidence`` 非空（不选边，双方 CONFLICTED）；
  * 条件并存（default 10:00 / 客户现场 16:00）经代理 observe →
    CONDITIONAL_ALTERNATIVES 双 ACTIVE，不进 conflicts[]；
  * 代理 corrections 走通：新 revision 回读（GET /records/{ref} 经代理）、
    affected_refs 含冲突对方；同 request_id 重放幂等（同 change_id）；
  * expected_revision 不符 → 409 REVISION_CONFLICT 同码透传
    （proxy 错误映射保持同码：detail.error 保留服务端 code）。

隔离规则同 harness：全部 TEST 事件类、主体 = atlas-fixture，不触生产路径
（harness._refuse_production_env 兜底）。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \
    -m pytest core/tests/unified_memory -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import uuid

import pytest

from tests.unified_memory.harness import UMHarness

SUBJECT = "atlas-fixture"          # harness 绑定主体（_memoryos_env）
UID = uuid.uuid4().hex[:8]         # 每次运行的种子命名空间（会话级 harness 复用）
HKT = "Asia/Hong_Kong"


def _context(harness: UMHarness, session: str) -> dict:
    return {**harness.default_context(), "runtime_session_id": session}


def _structured_obs(object_id: str, text: str, key: str, value: str, *,
                    occurred_at: str, **content_extra) -> dict:
    from atlas.memory.unified_client import observation_content_hash

    content = {"text": text, "key": key, "value": value}
    content.update(content_extra)
    obs = {
        "source_event_id": f"atlas:ATLAS_USER_MESSAGE:{object_id}:1:UPSERT",
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": object_id,
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": occurred_at,
        "source_timezone": HKT,
        "time_status": "KNOWN",
        "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": content,
        "locator": {"kind": "MESSAGE", "value": "chat-proxy/" + object_id},
        "media_refs": [],
        "derived_from": [],
    }
    obs["content_hash"] = observation_content_hash(obs)
    return obs


def _observe_via_proxy(harness: UMHarness, observations: list[dict],
                       session: str) -> dict:
    body = {
        "contract_version": "UM-WIN-1.0",
        "event_class": "TEST",
        "context": _context(harness, session),
        "observations": observations,
    }
    r = harness.api("POST", "/api/unified-memory/observe", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _recall_via_proxy(harness: UMHarness, query: str) -> dict:
    body = {
        "context": _context(harness, f"conflict-proxy-recall-{UID}"),
        "query": query,
        "purpose": "CONVERSATION",
    }
    r = harness.api("POST", "/api/unified-memory/recall", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _corrections_via_proxy(harness: UMHarness, request_id: str, target_ref: str,
                           expected_revision: int, replacement: dict):
    body = {
        "context": _context(harness, f"conflict-proxy-corr-{UID}"),
        "request_id": request_id,
        "target_ref": target_ref,
        "expected_revision": expected_revision,
        "replacement": replacement,
        "source": {"note": "atlas proxy test"},
    }
    return harness.api("POST", "/api/unified-memory/corrections", json=body)


def _get_record_via_proxy(harness: UMHarness, record_ref: str) -> dict:
    r = harness.api("GET", f"/api/unified-memory/records/{record_ref}")
    assert r.status_code == 200, r.text
    return r.json()


def _seed_unresolved_pair(harness: UMHarness, tag: str) -> tuple[str, str]:
    """传闻冲突：同 key 两值、陈述时刻可分但无变更证据/无条件 → UNRESOLVED。"""
    key = f"proxy:contract_day:{tag}"
    ack_a = _observe_via_proxy(
        harness,
        [_structured_obs(f"pcf-a-{tag}", "我确定合同是周一签", key, "周一",
                         occurred_at="2026-09-15T10:00:00+08:00")],
        f"conflict-proxy-{tag}-a")
    ack_b = _observe_via_proxy(
        harness,
        [_structured_obs(f"pcf-b-{tag}", "不对，合同肯定是周二签", key, "周二",
                         occurred_at="2026-09-15T10:05:00+08:00")],
        f"conflict-proxy-{tag}-b")
    assert ack_b["formation"]["results"][0]["kind"] == "UNRESOLVED"
    target_ref = ack_a["formation"]["results"][0]["record_ref"]
    partner_ref = ack_b["formation"]["results"][0]["record_ref"]
    return target_ref, partner_ref


@pytest.mark.integration
def test_conflict_proxy_recall_surfaces_unresolved_conflict(um: UMHarness):
    """seed conflict → 代理 recall 拿到 conflicts（UNRESOLVED + missing_evidence）。"""
    tag = f"recall-{UID}"
    target_ref, partner_ref = _seed_unresolved_pair(um, tag)

    payload = _recall_via_proxy(um, "该按哪个约定办")
    assert payload["conflicts"], "代理 recall 必须透出未决冲突"
    unresolved = payload["conflicts"][0]
    assert unresolved["kind"] == "UNRESOLVED"
    assert set(unresolved["record_refs"]) == {target_ref, partner_ref}
    assert unresolved["missing_evidence"], "冲突条目必须说明缺什么才能裁决"
    assert payload["missing_evidence"], "顶层 missing_evidence 同步提升（判据原样）"
    reasons = {entry["reason"] for entry in unresolved["missing_evidence"]}
    assert "NO_CORRECTION_MARKER" in reasons
    # 不选边：双方 CONFLICTED，都不冒充确定答案进 context_items
    values = [item.get("content", {}).get("value") for item in payload["context_items"]
              if isinstance(item.get("content"), dict)]
    assert "周一" not in values and "周二" not in values


@pytest.mark.integration
def test_conflict_proxy_conditional_alternatives_coexist(um: UMHarness):
    """条件偏好并存经代理 observe → CONDITIONAL_ALTERNATIVES：双 ACTIVE、
    applicability 各自标注、不进 conflicts[]。"""
    tag = f"cond-{UID}"
    key = f"proxy:meeting_start:{tag}"
    ack_a = _observe_via_proxy(
        um, [_structured_obs(f"pcm-a-{tag}", "周一上午周会安排在 10 点", key, "10:00",
                             occurred_at="2026-09-14T09:00:00+08:00")],
        f"conflict-proxy-{tag}-a")
    ack_b = _observe_via_proxy(
        um, [_structured_obs(f"pcm-b-{tag}", "要去客户现场就改到下午 4 点", key, "16:00",
                             occurred_at="2026-09-14T09:01:00+08:00",
                             applicability={"condition": "客户现场"})],
        f"conflict-proxy-{tag}-b")
    assert ack_b["formation"]["results"][0]["kind"] == "CONDITIONAL_ALTERNATIVES"
    default_ref = ack_a["formation"]["results"][0]["record_ref"]
    default_record = _get_record_via_proxy(um, default_ref)
    assert default_record["lifecycle"] == "ACTIVE"
    assert default_record["applicability"].get("default") is True
    conditional_ref = [ref for ref
                       in ack_b["formation"]["results"][0]["record_refs"]
                       if ref != default_ref][0]
    conditional_record = _get_record_via_proxy(um, conditional_ref)
    assert conditional_record["lifecycle"] == "ACTIVE"
    assert conditional_record["applicability"]["condition"] == "客户现场"

    payload = _recall_via_proxy(um, "周会几点")
    assert all(c["kind"] != "CONDITIONAL_ALTERNATIVES" for c in payload["conflicts"])


@pytest.mark.integration
def test_conflict_proxy_corrections_roundtrip_and_idempotent_replay(um: UMHarness):
    """代理 corrections 走通：新 revision 回读、affected_refs 含冲突对方；
    同 request_id 重放幂等（代理对 202/200 统一 200 返回，语义看 body）。"""
    tag = f"corr-{UID}"
    target_ref, partner_ref = _seed_unresolved_pair(um, tag)

    fresh = _corrections_via_proxy(
        um, f"pcorr-{tag}", target_ref, 1, {"value": "周三（邮件为准）"})
    assert fresh.status_code == 200, fresh.text
    ack = fresh.json()
    assert ack["acknowledged"] is True and ack["replayed"] is False
    assert ack["revision"] == 2 and ack["prev_revision"] == 1
    assert partner_ref in ack["affected_refs"], "affected_refs 必须含冲突对方"

    corrected = _get_record_via_proxy(um, target_ref)
    assert corrected["record_revision"] == 2
    assert corrected["content"]["value"] == "周三（邮件为准）"
    assert corrected["lifecycle"] == "ACTIVE"
    assert _get_record_via_proxy(um, partner_ref)["lifecycle"] == "INVALIDATED"

    replay = _corrections_via_proxy(
        um, f"pcorr-{tag}", target_ref, 1, {"value": "周三（邮件为准）"})
    assert replay.status_code == 200, replay.text
    replay_ack = replay.json()
    assert replay_ack["replayed"] is True
    assert replay_ack["change_id"] == ack["change_id"]
    assert replay_ack["affected_refs"] == ack["affected_refs"]
    assert _get_record_via_proxy(um, target_ref)["record_revision"] == 2

    # 裁决后冲突面清空
    payload = _recall_via_proxy(um, "该按哪个约定办")
    reported = {ref for c in payload["conflicts"] for ref in c["record_refs"]}
    assert target_ref not in reported and partner_ref not in reported


@pytest.mark.integration
def test_conflict_proxy_corrections_revision_conflict_409_passthrough(um: UMHarness):
    """expected_revision 不符 → 服务端 409 REVISION_CONFLICT，代理同码透传
    （detail.error 保留服务端错误码）。"""
    tag = f"c409-{UID}"
    target_ref, _partner_ref = _seed_unresolved_pair(um, tag)
    r = _corrections_via_proxy(um, f"pcorr-409-{tag}", target_ref, 99,
                               {"value": "随便改"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "REVISION_CONFLICT"
    assert detail["details"]["current"] == 1
    assert detail["details"]["expected"] == 99
    # 409 之后原记录未被改动
    assert _get_record_via_proxy(um, target_ref)["record_revision"] == 1
