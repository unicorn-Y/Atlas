"""Introspection surface: provider registry shape and the ledger parser.

Two real defects are pinned here.

1. The governance parser understood only ``## [L1] 标题`` headings, while the
   atlas-ledger skill it is built for writes ``- [L1] (seen 2x, severity: high)``
   list items. A ledger in the documented format parsed to **zero clauses**, and
   zero clauses reads as "no rule applies" — the most expensive wrong answer a
   governance surface can give.

2. ``check`` tokenised on non-word characters, so a whole Chinese sentence became
   one token and could never match. Every Chinese query answered "no rules", for
   the same reason.

Both are silent: nothing raised, nothing logged, the answer was just empty.
"""

from __future__ import annotations

import pytest

from atlas.introspect import registry
from atlas.introspect.providers import governance

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_providers_shape_and_uniqueness() -> None:
    listed = registry.list_providers()
    ids = [p["id"] for p in listed["providers"]]
    assert ids, "没有注册任何 introspection provider"
    assert len(ids) == len(set(ids)), f"provider id 重复：{ids}"
    assert listed["count"] == len(ids)
    assert listed["method_count"] == sum(len(p["methods"]) for p in listed["providers"])


@pytest.mark.unit
def test_every_provider_method_has_a_unique_name_and_schema() -> None:
    for provider in registry.providers():
        names = [m.name for m in provider.methods]
        assert len(names) == len(set(names)), f"{provider.id} 的方法名重复：{names}"
        for method in provider.methods:
            assert method.name and method.summary, f"{provider.id}.{method.name} 缺少说明"
            # Every method must declare an object schema; a free-form input would
            # make `query` unable to reject a typo'd argument.
            assert method.input_schema.get("type") == "object", (
                f"{provider.id}.{method.name} 的 input_schema 不是 object"
            )


@pytest.mark.unit
async def test_unknown_provider_and_method_raise() -> None:
    with pytest.raises(registry.QueryError):
        await registry.query("no-such-provider", "list")
    with pytest.raises(registry.QueryError):
        await registry.query("governance", "no-such-method")


# ---------------------------------------------------------------------------
# governance parser
# ---------------------------------------------------------------------------

#: Byte-for-byte the shape atlas-ledger v2.2 §4 documents, including the wrapped
#: INSTEAD line and the parenthesised metadata.
SKILL_FORM = """# Atlas Ledger

## Confirmed Clauses
- [L1] (seen 2x, severity: high)
  WHEN:    硬性 Must-Do 的后端部分受阻
  DON'T:   用前端 mock 冒充完成
  INSTEAD: 停下来披露阻塞点，让用户决定
           继续原目标还是改方案
  Source:  P3 Final Audit

## Provisional Observations
- [O1] (seen 1x)
  WHEN:    某个要求的测试失败
  DON'T:   削弱断言让它通过
  INSTEAD: 报告失败
  Source:  P2 Deviation Notice
"""

HEADING_FORM = """## Clauses
### [L7] 标题形式
- WHEN: h
- DON'T: i
- INSTEAD: j
- Source: P9
"""


@pytest.mark.unit
def test_skill_format_parses_all_clauses() -> None:
    parsed = governance._parse(SKILL_FORM)
    ids = [c["id"] for c in parsed["clauses"]]
    assert ids == ["L1", "O1"]
    assert parsed["sections"] == ["Confirmed Clauses", "Provisional Observations"]
    l1 = parsed["clauses"][0]
    assert l1["kind"] == "clause"
    assert parsed["clauses"][1]["kind"] == "observation"
    assert l1["when"] == "硬性 Must-Do 的后端部分受阻"
    assert l1["dont"] == "用前端 mock 冒充完成"
    assert l1["fields"]["severity"] == "high"
    assert l1["fields"]["seen"] == "2x"
    assert l1["fields"]["Source"] == "P3 Final Audit"


@pytest.mark.unit
def test_wrapped_value_keeps_its_tail() -> None:
    """The wrapped second line of INSTEAD must not be filed under ``extra``."""
    l1 = governance._parse(SKILL_FORM)["clauses"][0]
    assert "继续原目标还是改方案" in l1["instead"], (
        f"INSTEAD 被截断了：{l1['instead']!r}"
    )
    assert l1["extra"] == [], f"续行被误归到 extra：{l1['extra']}"


@pytest.mark.unit
def test_heading_form_still_parses() -> None:
    """Supporting the skill format must not drop the heading form."""
    (clause,) = governance._parse(HEADING_FORM)["clauses"]
    assert clause["id"] == "L7"
    assert clause["title"] == "标题形式"
    assert (clause["when"], clause["dont"], clause["instead"]) == ("h", "i", "j")


@pytest.mark.unit
def test_metadata_is_not_part_of_the_title() -> None:
    first = governance._parse(SKILL_FORM)["clauses"][0]
    assert "seen" not in first["title"]
    assert "severity" not in first["title"]


@pytest.mark.unit
def test_terms_splits_chinese_into_bigrams_and_keeps_latin_words() -> None:
    assert governance._terms("后端服务") == ["后端", "端服", "服务"]
    terms = governance._terms("port_guard.py 冲突")
    assert "port_guard" in terms and "冲突" in terms
    assert governance._terms("a b c") == [], "单字符 token 会命中几乎所有条款"
    # A file extension is a legitimate two-letter token; the point of the
    # assertion above is only that *single* characters are dropped.
    assert "py" in terms


@pytest.mark.unit
def test_chinese_action_matches() -> None:
    """The bug: a Chinese action used to tokenise to one unmatchable token."""
    terms = governance._terms("启动后端时端口被占了")
    assert len(terms) > 1
    haystack = "启动后端时端口被别的进程占了"
    assert any(term in haystack for term in terms)
