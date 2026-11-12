"""Tests for :mod:`atlas.engine.kernel.tool_pruning`.

The module is the correctness boundary for "which tools does the model see
this turn", so the properties that matter are the boring ones: same input,
same output, every time; the budget is a real ceiling; ``always_keep`` really
is always kept; de-duplication is first-wins; and a Chinese message still
reaches the tools that can serve it.
"""

from __future__ import annotations

import json

import pytest

from atlas.engine.kernel.tool_pruning import (
    DEFAULT_BUDGET,
    MIN_OFFERED,
    TIER_ORDER,
    bucket_of,
    explain_selection,
    family_of,
    merge_schemas,
    normalize_tier,
    schema_name,
    select_tools,
    select_tools_for_tier,
    tier_key,
    tokenize,
)

pytestmark = pytest.mark.unit


def _tool(name: str, description: str = "", params: dict | None = None) -> dict:
    """Build a minimal OpenAI-style function schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or f"The {name} tool.",
            "parameters": params or {"type": "object", "properties": {}},
        },
    }


def _pool(*names: str) -> list[dict]:
    return [_tool(name) for name in names]


def _names(schemas: list[dict]) -> list[str]:
    return [schema_name(schema) for schema in schemas]


# --- merge_schemas ---------------------------------------------------------

def test_merge_schemas_keeps_first_occurrence_by_name():
    first = _tool("read_file", "catalog wins")
    second = _tool("read_file", "kernel loses")
    other = _tool("grep", "only once")

    merged = merge_schemas([first, other], [second])

    assert _names(merged) == ["grep", "read_file"]
    winner = next(item for item in merged if schema_name(item) == "read_file")
    assert winner["function"]["description"] == "catalog wins"
    assert len(merged) == 2


def test_merge_schemas_leftmost_list_has_precedence():
    left = _tool("exec_command", "left")
    right = _tool("exec_command", "right")

    assert merge_schemas([left], [right])[0]["function"]["description"] == "left"
    assert merge_schemas([right], [left])[0]["function"]["description"] == "right"


def test_merge_schemas_returns_sorted_by_default():
    merged = merge_schemas(_pool("zebra", "alpha", "mike"))
    assert _names(merged) == ["alpha", "mike", "zebra"]


def test_merge_schemas_preserves_insertion_order_when_asked():
    merged = merge_schemas(_pool("zebra", "alpha", "mike"), sort=False)
    assert _names(merged) == ["zebra", "alpha", "mike"]


def test_merge_schemas_tolerates_none_and_malformed_entries():
    merged = merge_schemas(None, [_tool("grep")], [], [{"function": {}}, "junk", None])
    assert _names(merged) == ["grep"]


def test_merge_schemas_matches_kernel_first_wins_precedent():
    """The kernel layered catalog-over-kernel before; keep that exact rule."""
    seen: dict[str, dict] = {}
    historical = []
    for schema in [*_pool("a", "b"), *_pool("b", "c")]:
        name = schema_name(schema)
        if name not in seen:
            seen[name] = schema
            historical.append(name)

    merged = merge_schemas(_pool("a", "b"), _pool("b", "c"), sort=False)
    assert _names(merged) == historical


# --- determinism -----------------------------------------------------------

def test_select_tools_is_deterministic_across_runs():
    pool = _pool(
        "read_file", "grep", "glob", "exec_command", "memory_search",
        "browser_navigate", "android_build_app", "web_fetch", "todo_list",
        "update_plan", "lsp_diagnostics", "view_image",
    )
    kwargs = dict(message="帮我修一下 read_file 的报错", workspace="/repo/app.py",
                  recent_tools=("grep",), role="general", always_keep=("memory_search",))

    first = select_tools(pool, **kwargs)
    second = select_tools(pool, **kwargs)

    assert _names(first) == _names(second)
    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)


def test_select_tools_is_deterministic_under_input_reordering():
    """Score ties must break on name, never on input or set ordering."""
    base = _pool("alpha_tool", "beta_tool", "gamma_tool", "delta_tool")

    forward = _names(select_tools(base, message="unrelated words", budget=4))
    backward = _names(select_tools(list(reversed(base)), message="unrelated words", budget=4))

    assert forward == backward


def test_tokenize_is_stable_and_deduplicates():
    assert tokenize("Run the tests, run TESTS") == tokenize("Run the tests, run TESTS")
    tokens = tokenize("memory memory memory")
    assert tokens.count("memory") == 1


# --- always_keep -----------------------------------------------------------

def test_always_keep_tools_survive_a_zero_score():
    pool = _pool("memory_search", "android_build_app", "video_generate")
    kept = select_tools(
        pool, message="hello", budget=6, always_keep=("memory_search",),
    )
    assert "memory_search" in _names(kept)


def test_always_keep_names_that_are_absent_are_ignored():
    kept = select_tools(
        _pool("grep"), message="grep", budget=4, always_keep=("does_not_exist",),
    )
    assert _names(kept) == ["grep"]


def test_always_keep_is_still_bounded_by_budget():
    """``budget`` is a hard ceiling, not a hint. Rollback safety depends on it."""
    pool = _pool(*[f"keep_{index}" for index in range(10)])
    kept = select_tools(
        pool, message="x", budget=3, always_keep=tuple(_names(pool)),
    )
    assert len(kept) == 3


def test_explain_selection_marks_always_keep_reason():
    info = explain_selection(
        _pool("memory_search", "grep"), message="", budget=4,
        always_keep=("memory_search",),
    )
    assert info["tools"]["memory_search"]["reason"] == "always_keep"
    assert info["tools"]["memory_search"]["kept"] is True


# --- budget / floor --------------------------------------------------------

def test_budget_is_never_exceeded():
    pool = _pool(*[f"tool_{index}" for index in range(60)])
    for budget in (1, 5, 12, 24, 45):
        kept = select_tools(pool, message="tool", budget=budget)
        assert len(kept) <= budget
        assert len(kept) <= len(pool)


def test_budget_of_zero_returns_nothing():
    assert select_tools(_pool("grep", "glob"), message="grep", budget=0) == []


def test_floor_is_respected_for_a_signal_free_message():
    """A terse message must not starve the model below MIN_OFFERED."""
    pool = _pool(*[f"tool_{index}" for index in range(40)])
    kept = select_tools(pool, message="", budget=DEFAULT_BUDGET)
    assert len(kept) >= MIN_OFFERED
    assert len(kept) <= DEFAULT_BUDGET


def test_floor_does_not_exceed_available_tools():
    kept = select_tools(_pool("grep", "glob"), message="", budget=DEFAULT_BUDGET)
    assert len(kept) == 2


def test_budget_ceiling_holds_on_a_real_sized_pool():
    pool = _pool(*[f"tool_{index}" for index in range(97)])
    kept = select_tools(pool, message="修改 python 文件并跑测试", budget=DEFAULT_BUDGET)
    assert MIN_OFFERED <= len(kept) <= DEFAULT_BUDGET


# --- relevance -------------------------------------------------------------

def test_chinese_message_reaches_the_relevant_tools():
    pool = _pool(
        "exec_command", "read_file", "grep", "memory_search", "web_fetch",
        "video_generate", "music_generate", "text_to_speech", "android_build_app",
        "create_spreadsheet", "browser_navigate", "image_generate",
    )
    kept = _names(select_tools(
        pool, message="跑一下测试看看有没有报错", budget=12,
        always_keep=("memory_search",),
    ))
    assert "exec_command" in kept, kept


def test_chinese_memory_message_reaches_memory_tool():
    pool = _pool(
        "memory_search", "exec_command", "video_generate", "music_generate",
        "text_to_speech", "android_build_app",
    )
    kept = _names(select_tools(
        pool, message="记一下我喜欢什么", budget=8, always_keep=("memory_search",),
    ))
    assert "memory_search" in kept


def test_chinese_frontend_message_reaches_browser_and_style_tools():
    pool = _pool(
        "browser_navigate", "exec_command", "read_file", "video_generate",
        "music_generate", "android_build_app", "image_generate",
    )
    kept = _names(select_tools(
        pool, message="帮我改这个 React 组件的样式", workspace="/repo/src/App.tsx",
        budget=8,
    ))
    assert "browser_navigate" in kept, kept


def test_english_message_reaches_the_matching_tool():
    pool = _pool(
        "grep", "video_generate", "music_generate", "text_to_speech",
        "android_build_app", "create_spreadsheet",
    )
    kept = _names(select_tools(pool, message="please grep for the symbol", budget=8))
    assert kept[0] == "grep"


def test_recent_tools_are_boosted():
    pool = _pool("grep", "video_generate", "music_generate", "text_to_speech")
    kept = _names(select_tools(
        pool, message="continue", budget=6, recent_tools=("text_to_speech",),
    ))
    assert "text_to_speech" in kept


def test_workspace_extension_boosts_its_family():
    pool = _pool("android_build_app", "browser_navigate", "grep", "read_file")
    android = _names(select_tools(
        pool, message="修复启动问题", workspace="/repo/app/MainActivity.kt", budget=8,
    ))
    assert "android_build_app" in android, android


def test_unknown_schema_names_are_skipped_not_raised():
    kept = select_tools(
        [{"type": "function", "function": {}}, _tool("grep")],
        message="grep", budget=4,
    )
    assert _names(kept) == ["grep"]


# --- family / explanation --------------------------------------------------

def test_family_of_groups_the_known_duplicate_families():
    assert family_of("local_shell") == family_of("exec_command") == "shell"
    assert family_of("TaskCreate") == family_of("todo_list") == "planning"
    assert family_of("browser_use") == family_of("browser_navigate") == "browser"
    assert family_of("android_build_app") == "android"
    assert family_of("grep") == "files"


def test_family_cap_prevents_one_family_monopolising_the_budget():
    """With rivals available, one family may not take more than its cap."""
    pool = _pool(
        *[f"android_thing_{index}" for index in range(20)],
        *[f"helper_{index}" for index in range(20)],
    )
    info = explain_selection(
        pool, message="安卓 模拟器 构建 helper thing", budget=24, max_per_family=4,
    )
    android = [name for name in info["selected"] if name.startswith("android_")]
    assert len(android) <= 4, info["selected"]
    assert info["selected_count"] == 24


def test_floor_overrides_the_family_cap_when_nothing_else_is_available():
    """An under-provisioned pool is worse than a lopsided one."""
    pool = _pool(*[f"android_thing_{index}" for index in range(20)])
    info = explain_selection(
        pool, message="安卓 模拟器 构建", budget=24, max_per_family=4,
    )
    assert info["selected_count"] == MIN_OFFERED
    assert any(detail.get("reason", "").endswith("+floor")
               for detail in info["tools"].values())


def test_explain_selection_accounts_for_every_tool():
    pool = _pool("grep", "glob", "video_generate", "memory_search")
    info = explain_selection(pool, message="grep", budget=4, always_keep=("memory_search",))

    assert info["total"] == len(pool)
    assert info["selected_count"] + info["dropped_count"] == info["total"]
    assert set(info["selected"]) | set(info["dropped"]) == set(_names(pool))
    assert set(info["tools"]) == set(_names(pool))


def test_explain_selection_reports_a_score_and_reason_for_each_tool():
    info = explain_selection(_pool("grep", "music_generate"), message="grep", budget=4)
    for name, detail in info["tools"].items():
        assert isinstance(detail["score"], (int, float)), name
        assert detail["reason"], name
        assert isinstance(detail["signals"], dict), name


def test_explain_selection_explains_a_drop():
    info = explain_selection(
        _pool(*[f"tool_{index}" for index in range(30)]), message="tool_1", budget=4,
    )
    dropped = [name for name, detail in info["tools"].items() if not detail["kept"]]
    assert dropped
    assert all(info["tools"][name]["reason"] for name in dropped)


# --- purity ----------------------------------------------------------------

def test_select_tools_does_not_mutate_its_input():
    pool = _pool("grep", "memory_search", "video_generate")
    snapshot = json.dumps(pool, ensure_ascii=False, sort_keys=True)

    select_tools(pool, message="grep", budget=4, always_keep=("memory_search",))

    assert json.dumps(pool, ensure_ascii=False, sort_keys=True) == snapshot
    assert _names(pool) == ["grep", "memory_search", "video_generate"]


def test_select_tools_does_not_depend_on_process_environment(monkeypatch):
    pool = _pool("grep", "memory_search", "video_generate", "android_build_app")
    kwargs = dict(message="跑一下测试", budget=8, always_keep=("memory_search",))

    baseline = _names(select_tools(pool, **kwargs))
    monkeypatch.setenv("ATLAS_TOOL_PRUNING", "1")
    monkeypatch.setenv("ATLAS_WORKSPACE", "/somewhere/else")
    assert _names(select_tools(pool, **kwargs)) == baseline


# --- real pool -------------------------------------------------------------

def test_real_kernel_pool_shrinks_substantially():
    """Guard the actual objective: 97 schemas in, a small pool out."""
    from atlas.engine.kernel.tools import kernel_tool_schemas

    pool = kernel_tool_schemas(include_workflow=True)
    before_count = len(pool)
    before_bytes = len(json.dumps(pool, ensure_ascii=False))

    kept = select_tools(
        pool,
        message="帮我改这个 React 组件的样式",
        workspace="/repo/src/App.tsx",
        budget=DEFAULT_BUDGET,
        always_keep=("memory_search", "tool_search", "workflow"),
    )
    after_bytes = len(json.dumps(kept, ensure_ascii=False))

    assert before_count >= 90
    assert MIN_OFFERED <= len(kept) <= DEFAULT_BUDGET
    assert after_bytes < before_bytes / 2, (after_bytes, before_bytes)
    assert "memory_search" in _names(kept)
    assert "tool_search" in _names(kept)

# --- tier selection (cache stability) --------------------------------------
#
# The point of tiers is that the tool block changes RARELY. A per-message pool
# saves ~1.08x of tokens but breaks the cached prompt prefix and costs ~6.2x,
# so the property under test is not "the pool is sharp for this message" but
# "the pool is identical until the kind of work changes".

_TIER_MESSAGES = (
    "帮我改这个 React 组件的样式",
    "记一下我喜欢什么",
    "跑一下测试",
    "今天天气不错",
    "对比这两个方案的设计取舍",
    "这个函数为什么这么写",
    "你好",
    "remember that I prefer tabs",
    "fix the failing test",
    "what do you think about this approach",
)


def _tier_pool_bytes(tier: str, pool=None) -> bytes:
    pool = _pool(*_names(kernel_pool)) if pool is None else pool
    selected = select_tools_for_tier(pool, tier)
    return json.dumps(selected, ensure_ascii=False, sort_keys=True).encode()


@pytest.fixture(scope="module")
def kernel_pool():  # noqa: N802 - module-scoped fixture
    from atlas.engine.kernel.tools import kernel_tool_schemas

    return kernel_tool_schemas(include_workflow=True)


def test_tier_key_is_always_a_known_tier():
    for message in _TIER_MESSAGES:
        assert tier_key(message) in TIER_ORDER


def test_tier_key_ignores_history_and_ordering():
    """Only the message text decides; repeated calls cannot drift."""
    message = "帮我改这个 React 组件的样式"
    first = tier_key(message)
    for _ in range(100):
        assert tier_key(message) == first


def test_tier_key_maps_unknown_and_empty_to_default():
    assert tier_key("") == "default"
    assert normalize_tier("") == "default"
    assert normalize_tier("nonsense") == "default"
    assert normalize_tier("CODE") == "code"


def test_same_tier_pool_is_byte_identical_across_100_calls(kernel_pool):
    """The cache-stability contract: one tier, one byte image."""
    for tier in TIER_ORDER:
        baseline = _tier_pool_bytes(tier, kernel_pool)
        for _ in range(100):
            assert _tier_pool_bytes(tier, kernel_pool) == baseline


def test_same_tier_pool_is_independent_of_input_order(kernel_pool):
    import random

    shuffled = list(kernel_pool)
    random.Random(0).shuffle(shuffled)
    for tier in TIER_ORDER:
        assert _tier_pool_bytes(tier, shuffled) == _tier_pool_bytes(tier, kernel_pool)


def test_distinct_messages_with_same_tier_share_one_pool(kernel_pool):
    """Different wording, same kind of work -> same bytes, not just same size.

    This is the bug the tier mode exists to prevent: two tiers that both emit
    N tools can still differ byte-for-byte and each cost a full cache miss.
    """
    by_tier: dict[str, set[bytes]] = {}
    for message in _TIER_MESSAGES:
        tier = tier_key(message)
        by_tier.setdefault(tier, set()).add(_tier_pool_bytes(tier, kernel_pool))
    for tier, images in by_tier.items():
        assert len(images) == 1, f"tier {tier!r} produced {len(images)} pools"


def test_tier_pools_converge_to_three_buckets(kernel_pool):
    """Five tier names, three pools: the number of prefixes is what costs."""
    images = {_tier_pool_bytes(tier, kernel_pool) for tier in TIER_ORDER}
    assert len(images) == 3, "expected code / talk / default"
    assert bucket_of("memory") == bucket_of("discuss")
    assert bucket_of("chat") == bucket_of("default")
    assert _tier_pool_bytes("memory", kernel_pool) == _tier_pool_bytes("discuss", kernel_pool)
    assert _tier_pool_bytes("chat", kernel_pool) == _tier_pool_bytes("default", kernel_pool)


def test_tier_selection_ignores_environment(kernel_pool, monkeypatch):
    baseline = {t: _tier_pool_bytes(t, kernel_pool) for t in TIER_ORDER}
    monkeypatch.setenv("ATLAS_TOOL_PRUNING", "1")
    monkeypatch.setenv("ATLAS_WORKSPACE", "/somewhere/else")
    for tier in TIER_ORDER:
        assert _tier_pool_bytes(tier, kernel_pool) == baseline[tier]


def test_tier_selection_respects_budget_and_always_keep(kernel_pool):
    for tier in TIER_ORDER:
        kept = select_tools_for_tier(kernel_pool, tier, budget=12, always_keep=("memory_search",))
        assert len(kept) <= 12
        assert "memory_search" in _names(kept)


def test_tier_pools_are_smaller_than_the_full_table(kernel_pool):
    full = len(json.dumps(kernel_pool, ensure_ascii=False))
    for tier in TIER_ORDER:
        assert len(select_tools_for_tier(kernel_pool, tier)) < len(kernel_pool)
        assert len(_tier_pool_bytes(tier, kernel_pool)) < full / 2


def test_code_tier_prefers_code_tooling_over_media():
    """A code turn must not be crowded out by android/media families."""
    pool = _pool(
        "glob", "grep", "exec_command", "powershell", "lsp_diagnostics",
        "build_repo_map", "memory_search", "update_plan",
        "android_build_app", "image_edit", "video_generate", "music_generate",
    )
    kept = _names(select_tools_for_tier(pool, "code", budget=8))
    assert {"glob", "grep", "exec_command", "lsp_diagnostics"} <= set(kept)
    assert "image_edit" not in kept
    assert "music_generate" not in kept


def test_discuss_tier_prefers_planning_tools():
    pool = _pool(
        "update_plan", "TaskCreate", "TodoWrite", "memory_search", "x_search",
        "glob", "grep", "exec_command", "android_build_app",
    )
    kept = _names(select_tools_for_tier(pool, "discuss", budget=8))
    assert "update_plan" in kept
    assert "android_build_app" not in kept
