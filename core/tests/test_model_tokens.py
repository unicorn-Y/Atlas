from __future__ import annotations

import tiktoken

from atlas.models.tokens import count_tokens, estimate_tokens


def test_count_tokens_prefers_provider_input_usage() -> None:
    assert count_tokens("ignored", model="gpt-4o", usage={"input_tokens": 37}) == 37
    assert count_tokens("ignored", model="gpt-4o", usage={"prompt_tokens": 19}) == 19


def test_estimate_tokens_uses_tiktoken_for_mixed_english_and_chinese() -> None:
    sample = "Plan the migration carefully, then 验证每个接口的实际结果。"
    expected = len(tiktoken.encoding_for_model("gpt-4o").encode(sample))

    assert estimate_tokens(sample, model="gpt-4o") == expected
