"""Unit tests for the absorbed DSH credential grammar."""

from __future__ import annotations

import pytest

from atlas.models.credential_grammar import (
    ApiKeyVerdict,
    credential_key,
    credential_key_id,
    credential_key_scope,
    credential_ref,
    is_credential_key_segment,
    is_credential_ref_name,
    normalize_api_key,
    parse_credential_key,
    redact_api_key,
    require_api_key,
)


@pytest.mark.unit
@pytest.mark.parametrize("name", ["API_KEY", "_PRIVATE", "A1", "deepseek_api_key"])
def test_valid_credential_refs(name):
    assert credential_ref(name) == name
    assert is_credential_ref_name(name) is True


@pytest.mark.unit
@pytest.mark.parametrize("name", ["", "1ABC", "A-B", "A.B", "A B", None, 7])
def test_invalid_credential_refs(name):
    assert is_credential_ref_name(name) is False
    with pytest.raises(TypeError):
        credential_ref(name)


@pytest.mark.unit
@pytest.mark.parametrize("segment", ["llm-pi-ai", "provider", "a1"])
def test_valid_key_segments(segment):
    assert is_credential_key_segment(segment) is True


@pytest.mark.unit
@pytest.mark.parametrize("segment", ["", "Upper", "a_b", "-start", "a/b", None])
def test_invalid_key_segments(segment):
    assert is_credential_key_segment(segment) is False


@pytest.mark.unit
def test_credential_key_join_and_parse():
    key = credential_key("llm-pi-ai", "route-1")
    assert key == "llm-pi-ai/route-1"
    assert parse_credential_key(key) == key
    assert credential_key_scope(key) == "llm-pi-ai"
    assert credential_key_id(key) == "route-1"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["a/b/c", "A/b", "a/B", "a", ""])
def test_bad_joined_keys_are_rejected(bad):
    with pytest.raises(TypeError):
        parse_credential_key(bad)


@pytest.mark.unit
def test_api_key_is_trimmed_and_accepted():
    verdict = normalize_api_key("  sk-abc-123  ")
    assert verdict == ApiKeyVerdict(True, value="sk-abc-123")


@pytest.mark.unit
@pytest.mark.parametrize("raw,reason", [
    ("", "empty"),
    ("   \n\t", "empty"),
    ("a b", "illegal_characters"),
    ("密钥", "illegal_characters"),
    ("sk-abc\nnext", "illegal_characters"),
    (None, "not_a_string"),
    (123, "not_a_string"),
])
def test_api_key_rejections(raw, reason):
    verdict = normalize_api_key(raw)
    assert verdict.ok is False
    assert verdict.reason == reason


@pytest.mark.unit
def test_require_api_key_raises_without_echoing_the_secret():
    secret = "sk-very-secret value"
    with pytest.raises(ValueError) as excinfo:
        require_api_key(secret)
    assert secret not in str(excinfo.value)


@pytest.mark.unit
def test_redaction_keeps_only_edge_fragments():
    assert redact_api_key("sk-1234567890") == "sk-1…7890"
    assert redact_api_key("abc") == "***"
    assert redact_api_key("") == ""
    assert redact_api_key(None) == ""