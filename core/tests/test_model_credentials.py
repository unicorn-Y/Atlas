"""AtlasCredentialPool（C5 B2）——多密钥轮换池单元测试 + hermes 协议兼容测试。

注入内存假凭据库（FakeKeyringStore）与假时钟（FakeClock），不碰真实 keyring 与
真实 settings；密钥原文只存在于内存假库里，绝不落 settings/输出。
"""

from __future__ import annotations

import json

import pytest

from atlas.config import load_user_settings, save_user_settings
from atlas.models.credentials import (
    EXHAUSTED_TTL_401_SECONDS,
    EXHAUSTED_TTL_429_SECONDS,
    EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS,
    AtlasCredentialPool,
)

PID = "deepseek"  # catalog id == hermes provider id，便于协议测试对齐


class FakeClock:
    """注入 AtlasCredentialPool(now=...) 的假时钟（epoch 秒）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeKeyringStore:
    """内存假凭据库（接口同 atlas.telegram.KeyringCredentialStore）。"""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._secrets.get(key)

    def set(self, key: str, value: str) -> None:
        self._secrets[key] = value

    def delete(self, key: str) -> None:
        self._secrets.pop(key, None)


class StubAgent:
    """按 hermes client_lifecycle.py:951 _swap_credential 实际读取的属性构造的 agent 替身。"""

    def __init__(
        self, pool: AtlasCredentialPool, *, api_key: str, provider: str,
        base_url: str, model: str | None,
    ) -> None:
        self._credential_pool = pool
        self._credential_pool_entry_id = None
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def _swap_credential(self, entry) -> bool:
        # 与 hermes _swap_credential 相同的属性读取与赋值（替身不重建 HTTP 客户端）。
        self.api_key = getattr(entry, "runtime_api_key", None) or getattr(entry, "access_token", "")
        base = getattr(entry, "runtime_base_url", None) or getattr(entry, "base_url", None)
        self.base_url = base or self.base_url
        self._credential_pool_entry_id = getattr(entry, "id", None)
        return True


@pytest.fixture
def isolated(tmp_path, monkeypatch) -> None:
    """settings 读写隔离到临时文件（credentials 模块经 atlas.config 读写）。"""
    from atlas import config

    monkeypatch.setattr(config, "USER_SETTINGS_PATH", tmp_path / "user-settings.json")


def make_pool(
    key_ids: list[str],
    *,
    pid: str = PID,
    clock: FakeClock | None = None,
    store: FakeKeyringStore | None = None,
) -> tuple[AtlasCredentialPool, FakeClock, FakeKeyringStore]:
    """预置 settings（含一个无关键验证合并写）+ 假凭据库原文，返回建好的池。"""
    clock = clock or FakeClock()
    store = store or FakeKeyringStore()
    doc: dict = {"custom_models": [{"id": "keep-me"}], "selected_model": "claude-opus-4"}
    providers = doc.setdefault("providers", {})
    providers[pid] = {
        "base_url": None,
        "keys": [
            {"id": key_id, "label": f"密钥{index + 1}", "added_at": "2026-10-02T00:00:00+00:00"}
            for index, key_id in enumerate(key_ids)
        ],
    }
    save_user_settings(doc)
    for key_id in key_ids:
        store.set(f"atlas.provider.{pid}.key.{key_id}", f"sk-secret-{key_id}")
    pool = AtlasCredentialPool(pid, store=store, now=clock)
    return pool, clock, store


def settings_key_row(pid: str, key_id: str) -> dict:
    keys = load_user_settings()["providers"][pid]["keys"]
    return next(row for row in keys if row["id"] == key_id)


def entry(pool: AtlasCredentialPool, key_id: str):
    return next(e for e in pool.entries() if e.id == key_id)


# ---------------------------------------------------------------------------
# ① 双 key：select → key1；429 → mark_exhausted_and_rotate 返回 key2 且 key1 进入冷却
# ---------------------------------------------------------------------------

def test_select_fill_first_and_429_rotation(isolated) -> None:
    pool, clock, _store = make_pool(["k1", "k2"])

    assert pool.provider == PID
    assert pool.has_credentials() and pool.has_available()
    first = pool.select()
    assert first is not None and first.id == "k1"
    assert first.runtime_api_key == "sk-secret-k1"
    assert first.request_count == 1
    assert settings_key_row(PID, "k1")["request_count"] == 1

    next_entry = pool.mark_exhausted_and_rotate(
        status_code=429, api_key_hint=first.runtime_api_key, credential_id=first.id,
        error_context={"message": "rate limited"},
    )
    assert next_entry is not None and next_entry.id == "k2"
    assert next_entry.runtime_api_key == "sk-secret-k2"
    assert next_entry.request_count == 1
    assert pool.current() is not None and pool.current().id == "k2"
    assert pool.peek().id == "k2"

    k1 = entry(pool, "k1")
    assert k1.last_status == "exhausted"
    assert k1.cooldown_until == clock() + EXHAUSTED_TTL_429_SECONDS
    assert k1.last_error is not None and "429" in k1.last_error

    row = settings_key_row(PID, "k1")
    assert row["last_status"] == "exhausted"
    assert row["cooldown_until"] == clock() + EXHAUSTED_TTL_429_SECONDS
    assert row["request_count"] == 1

    # 合并写：无关键完好；密钥原文永不落 settings
    doc = load_user_settings()
    assert doc["custom_models"] == [{"id": "keep-me"}]
    assert doc["selected_model"] == "claude-opus-4"
    assert "sk-secret-" not in json.dumps(doc)


# ---------------------------------------------------------------------------
# ② 冷却到期恢复（fake now 前进）+ next_available_at
# ---------------------------------------------------------------------------

def test_cooldown_expiry_recovery(isolated) -> None:
    pool, clock, _store = make_pool(["k1", "k2"])
    pool.select()
    assert pool.mark_exhausted_and_rotate(status_code=429, api_key_hint="sk-secret-k1").id == "k2"
    # 双 key 全部冷却 → 无可用；next_available_at 给出最早恢复时刻
    assert pool.mark_exhausted_and_rotate(status_code=429, api_key_hint="sk-secret-k2") is None
    assert not pool.has_available()
    assert pool.next_available_at() == pytest.approx(clock() + EXHAUSTED_TTL_429_SECONDS)

    clock.advance(2 * 3600)
    assert pool.has_available()
    assert pool.next_available_at() is None
    recovered = pool.select()
    assert recovered is not None and recovered.id == "k1"
    assert recovered.last_status == "ok"
    assert recovered.cooldown_until is None
    assert recovered.runtime_api_key == "sk-secret-k1"
    row = settings_key_row(PID, "k1")
    assert row["last_status"] == "ok"
    assert "cooldown_until" not in row and "last_error" not in row


# ---------------------------------------------------------------------------
# ③ 协议兼容：真实 hermes recover_with_credential_pool 走 429 路径换 key
# ---------------------------------------------------------------------------

def test_hermes_recover_with_credential_pool_swaps_key(isolated) -> None:
    from agent.agent_runtime_helpers import recover_with_credential_pool
    from agent.credential_pool import credential_pool_matches_provider

    pool, clock, _store = make_pool(["k1", "k2"])
    agent = StubAgent(
        pool, api_key="sk-secret-k1", provider=PID,
        base_url="https://api.deepseek.com/v1", model="deepseek-chat",
    )
    # agent 构造期（hermes agent_init._finalize_routing）用同一谓词校验池归属
    assert credential_pool_matches_provider(pool, agent.provider, base_url=agent.base_url)

    recovered, has_retried_429 = recover_with_credential_pool(
        agent, status_code=429, has_retried_429=True, error_context={"message": "rate limited"},
    )
    assert recovered is True and has_retried_429 is False
    assert agent.api_key == "sk-secret-k2"
    assert agent._credential_pool_entry_id == "k2"
    k1 = entry(pool, "k1")
    # 带 model 的 429：只冷却 (key, model)，凭据级状态不动
    assert k1.last_status is None and k1.cooldown_until is None
    assert k1.model_cooldowns["deepseek-chat"] == clock() + EXHAUSTED_TTL_429_SECONDS

    # 第二次失败（model 置空走凭据级路径）：k2 整条进入 1h 冷却，池耗尽返回 None
    agent.model = None
    recovered2, _ = recover_with_credential_pool(
        agent, status_code=429, has_retried_429=True, error_context={"message": "rate limited"},
    )
    assert recovered2 is False
    k2 = entry(pool, "k2")
    assert k2.last_status == "exhausted"
    assert k2.cooldown_until == clock() + EXHAUSTED_TTL_429_SECONDS
    assert not pool.has_available()


# ---------------------------------------------------------------------------
# ④ 模型级冷却只影响该 model
# ---------------------------------------------------------------------------

def test_model_scoped_cooldown_only_affects_that_model(isolated) -> None:
    pool, clock, _store = make_pool(["k1", "k2"], pid="anthropic")
    assert pool.provider == "anthropic"
    pool.select()

    next_entry = pool.mark_exhausted_and_rotate(
        status_code=429, api_key_hint="sk-secret-k1",
        model="claude-opus-4", error_context={"message": "rate limited"},
    )
    assert next_entry is not None and next_entry.id == "k2"

    k1 = entry(pool, "k1")
    assert k1.cooldown_until is None and k1.last_status is None  # 凭据级状态未动
    assert set(k1.model_cooldowns) == {"claude-opus-4"}
    assert k1.model_cooldowns["claude-opus-4"] == clock() + EXHAUSTED_TTL_429_SECONDS
    persisted_cooldown = settings_key_row("anthropic", "k1")["model_cooldowns"]["claude-opus-4"]
    assert persisted_cooldown == clock() + EXHAUSTED_TTL_429_SECONDS

    # 只影响该 model：兄弟模型照常用 k1，该模型只能换 k2
    assert pool.has_available(model="claude-sonnet-4")
    assert pool.next_available_at(model="claude-sonnet-4") is None
    assert pool.select(model="claude-sonnet-4").id == "k1"
    assert pool.has_available(model="claude-opus-4")
    assert pool.select(model="claude-opus-4").id == "k2"
    # 不指定 model 的保守查询被任何活跃模型冷却阻塞（hermes 语义），k2 仍可用
    assert pool.has_available()


# ---------------------------------------------------------------------------
# ⑤ 401/403 → 5min；billing → 1h；唯一 key 非 billing → 60s
# ---------------------------------------------------------------------------

def test_401_403_short_and_billing_full_hour(isolated) -> None:
    pool, clock, _store = make_pool(["k1", "k2", "k3"])
    pool.select()

    assert pool.mark_exhausted_and_rotate(status_code=401, api_key_hint="sk-secret-k1").id == "k2"
    assert entry(pool, "k1").cooldown_until == clock() + EXHAUSTED_TTL_401_SECONDS

    assert pool.mark_exhausted_and_rotate(status_code=403, api_key_hint="sk-secret-k2").id == "k3"
    assert entry(pool, "k2").cooldown_until == clock() + EXHAUSTED_TTL_401_SECONDS

    assert pool.mark_exhausted_and_rotate(
        status_code=403, failure_reason="billing", api_key_hint="sk-secret-k3",
    ) is None  # 三个 key 全部冷却
    assert entry(pool, "k3").cooldown_until == clock() + EXHAUSTED_TTL_429_SECONDS


def test_sole_key_short_cooldown_unless_billing(isolated) -> None:
    pool, clock, _store = make_pool(["k1"])
    pool.select()
    # 唯一 key 非 billing：60s 短冷却，无处可换返回 None
    assert pool.mark_exhausted_and_rotate(status_code=429, api_key_hint="sk-secret-k1") is None
    assert entry(pool, "k1").cooldown_until == clock() + EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS
    assert not pool.has_available()

    clock.advance(EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS + 1)
    assert pool.has_available()
    assert pool.select().id == "k1"

    # billing（402 / failure_reason="billing"）不吃 60s 短冷却，整段 bench
    assert pool.mark_exhausted_and_rotate(
        status_code=429, failure_reason="billing", api_key_hint="sk-secret-k1",
    ) is None
    assert entry(pool, "k1").cooldown_until == clock() + EXHAUSTED_TTL_429_SECONDS


# ---------------------------------------------------------------------------
# 上游 reset 时刻优先于默认 TTL
# ---------------------------------------------------------------------------

def test_upstream_reset_at_and_retry_after_win(isolated) -> None:
    pool, clock, _store = make_pool(["k1", "k2"])
    pool.select()

    assert pool.mark_exhausted_and_rotate(
        status_code=429, api_key_hint="sk-secret-k1", error_context={"reset_at": clock() + 120},
    ).id == "k2"
    assert entry(pool, "k1").cooldown_until == clock() + 120

    assert pool.mark_exhausted_and_rotate(
        status_code=429, api_key_hint="sk-secret-k2",
        error_context={"message": "Please retry after 90 seconds"},
    ) is None
    assert entry(pool, "k2").cooldown_until == clock() + 90
