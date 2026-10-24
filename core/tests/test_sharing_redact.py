"""Tests for ``atlas.sharing.redact``: secret and user-path regex semantics.

Every assertion here mirrors an explicit regex fact, spelled out in the comment
above the test. Values are deterministic substring substitutions, so file paths
inside test inputs are made-up (``alice``/``bob``/``carol``) and never validated.
"""

from __future__ import annotations

import pytest

from atlas.sharing import redact

SK_16 = "sk-" + "a" * 16
GH_20 = "ghp_" + "a" * 20


def test_empty_string_returns_empty_string() -> None:
    # Neither pattern has an alternative that matches the empty string.
    assert redact("") == ""


@pytest.mark.parametrize("value", ["hello world", "   ", "password=short"])
def test_no_match_returns_input_unchanged(value: str) -> None:
    # No secret shape and no user-path shape: both .sub() calls replace nothing.
    assert redact(value) == value


def test_secret_rule_matches_sk_token() -> None:
    # ``sk-[A-Za-z0-9_-]{16,}`` needs at least 16 tail characters.
    assert redact(SK_16) == "[REDACTED]"


def test_secret_rule_matches_github_token() -> None:
    # ``gh[pousr]_[A-Za-z0-9_]{20,}``: p is one of p/o/u/s/r, tail needs 20+.
    assert redact(GH_20) == "[REDACTED]"


def test_secret_rule_matches_key_value_assignment() -> None:
    # ``(?:token|api[_-]?key|password|secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}``
    # consumes the key, the separator and the whole value.
    assert redact("password=hunter2hunter2") == "[REDACTED]"
    assert redact("token: abcdefgh") == "[REDACTED]"
    assert redact("api-key:abcdefgh") == "[REDACTED]"


def test_secret_keyword_is_case_insensitive() -> None:
    # The pattern carries inline ``(?i)``.
    assert redact("PASSWORD=abcdefgh123") == "[REDACTED]"
    assert redact("SECRET:abcdefgh") == "[REDACTED]"


def test_secret_value_shorter_than_eight_chars_is_kept() -> None:
    # ``{8,}`` is a hard floor: 7 characters must not be redacted.
    assert redact("password=1234567") == "password=1234567"
    assert redact("password=12345678") == "[REDACTED]"


def test_sk_token_shorter_than_sixteen_chars_is_kept() -> None:
    assert redact("sk-" + "a" * 15) == "sk-" + "a" * 15
    assert redact("sk-" + "a" * 16) == "[REDACTED]"


def test_github_token_shorter_than_twenty_chars_is_kept() -> None:
    assert redact("ghp_" + "a" * 19) == "ghp_" + "a" * 19


def test_secret_keyword_without_separator_is_kept() -> None:
    # The assignment branch requires ``[:=]``; a bare word never matches.
    assert redact("tokenize this") == "tokenize this"


def test_path_rule_matches_windows_user_dir() -> None:
    # ``[A-Z]:\\Users\\[^\\\s]+`` replaces drive + profile name with ``~``.
    assert redact("see C:\\Users\\alice\\notes.txt") == "see ~\\notes.txt"


def test_path_rule_matches_posix_home() -> None:
    # ``/home/[^/\s]+`` and ``/Users/[^/\s]+`` stop at the next slash.
    assert redact("open /home/bob/.ssh/id_rsa") == "open ~/.ssh/id_rsa"
    assert redact("/Users/carol/Downloads/a.txt") == "~/Downloads/a.txt"


def test_path_rule_preserves_surrounding_whitespace() -> None:
    # Only the matched span is replaced; padding is untouched.
    assert redact("  C:\\Users\\alice\\x  ") == "  ~\\x  "


def test_path_trailing_backslash_is_kept() -> None:
    # ``[^\\\s]+`` is greedy but stops before the separating backslash.
    assert redact("C:\\Users\\alice\\") == "~\\"


# ---------------------------------------------------------------------------
# Order sensitivity: ``_USER_PATH.sub`` wraps ``_SECRET.sub``, so the secret
# rule always runs first and its replacement text never reaches the path rule.
# ---------------------------------------------------------------------------


def test_order_secret_runs_first_and_swallows_the_path() -> None:
    # Secret rule wins: ``api_key=`` + value matches, the value (a path) is gone.
    # Reversing the order would yield ``api_key=~\k.txt`` and leak the path shape.
    assert redact("api_key=C:\\Users\\alice\\k.txt") == "[REDACTED]"
    assert redact("token: /home/bob/token.txt") == "[REDACTED]"
    assert redact("password=/Users/carol/data") == "[REDACTED]"


def test_order_path_replacement_text_is_not_rematched() -> None:
    # ``~`` inserted by the path rule contains no ``[:=]``, so the secret rule
    # (already finished) is unaffected; pre-existing text stays as-is.
    assert redact("~/x password=abcdefgh123") == "~/x [REDACTED]"


# ---------------------------------------------------------------------------
# Multiple and adjacent matches.
# ---------------------------------------------------------------------------


def test_multiple_paths_and_one_secret_all_redacted() -> None:
    assert redact("a C:\\Users\\alice\\a /home/bob/b and password=abcdefgh123") == (
        "a ~\\a ~/b and [REDACTED]"
    )


def test_adjacent_paths_redacted_separately() -> None:
    # ``[^\\\s]+`` ends at the next backslash, so the second match starts cleanly.
    assert redact("C:\\Users\\alice\\aC:\\Users\\bob\\b") == "~\\a~\\b"


def test_adjacent_sk_tokens_merge_into_one_match() -> None:
    # ``[A-Za-z0-9_-]{16,}`` is greedy over ``-``, so two tokens separated only
    # by nothing form a single longer match and produce one replacement.
    assert redact(SK_16 + "sk-" + "b" * 16) == "[REDACTED]"


def test_adjacent_assignments_merge_into_one_match() -> None:
    # ``[^\s'\"]{8,}`` spans the second ``password=`` too: one replacement.
    assert redact("password=abcdefgh123password=zzzzzzzzz") == "[REDACTED]"


def test_replacement_output_is_not_rescanned_for_paths() -> None:
    # ``[REDACTED]`` contains no user-path shape, so a literal in the input and
    # a real path each survive the correct way around.
    assert redact("[REDACTED] /home/bob/x") == "[REDACTED] ~/x"


# ---------------------------------------------------------------------------
# Known boundary semantics (documented, not necessarily desired).
# ---------------------------------------------------------------------------


def test_optional_quote_is_not_consumed_dangling_quote_is_kept() -> None:
    # ``['\"]?`` is optional and outside the value group, so the closing quote
    # of a quoted value is not part of the match and stays in the output.
    assert redact("api_key = 'abcdefgh123'") == "[REDACTED]'"


def test_keyword_matches_as_substring_without_word_boundary() -> None:
    # No ``\b`` around the keyword: ``prefixsk-`` keeps its ``prefix``.
    assert redact("prefix" + SK_16) == "prefix[REDACTED]"


def test_path_rule_consumes_the_whole_profile_segment() -> None:
    # ``[^/\s]+`` keeps consuming apostrophes, so they vanish with the match.
    assert redact("user /home/alice-o'brien/x") == "user ~/x"
