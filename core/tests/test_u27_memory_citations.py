from atlas.agent.run_phases import _extract_memory_citations, _infer_memory_citations


def test_infers_adopted_memory_ref_when_model_omits_marker() -> None:
    recall = "Atlas 记忆库里和这句话有关的记录：\n- The U27 personal fact is cobalt lantern [ref:u27-source@2026-10-25T10:00:00+00:00]"

    assert _infer_memory_citations(
        "The object was a lantern, and its color was cobalt.",
        recall,
        ["u27-source@2026-10-25T10:00:00+00:00"],
    ) == ["u27-source@2026-10-25T10:00:00+00:00"]


def test_does_not_infer_source_from_single_generic_word_or_unallowed_ref() -> None:
    recall = "- The preferred drink is tea [ref:private-source]"

    assert _infer_memory_citations("Tea is common.", recall, ["private-source"]) == []
    assert _infer_memory_citations("The preferred drink is tea.", recall, ["other-source"]) == []
    assert _infer_memory_citations(
        "That personal fact is unrelated.",
        "- My personal fact is stored here [ref:private-source]",
        ["private-source"],
    ) == []


def test_infers_copied_cjk_phrase() -> None:
    assert _infer_memory_citations(
        "你之前提过青瓷茶壶。",
        "- 你喜欢青瓷茶壶 [ref:cjk-source]",
        ["cjk-source"],
    ) == ["cjk-source"]


def test_explicit_marker_remains_filtered_to_allowed_refs() -> None:
    clean, refs = _extract_memory_citations(
        "The object is cobalt lantern. <!-- atlas-memory-citations: allowed, invented -->",
        ["allowed"],
    )

    assert clean == "The object is cobalt lantern."
    assert refs == ["allowed"]
