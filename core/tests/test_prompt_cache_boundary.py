"""Tests adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
tests/agent/test_prompt_cache_boundary.py.

The Hermes-specific skill and cron builders are not part of Atlas; these cases
cover the shared stable-prefix registry and request-local cache split.
"""

from atlas.agent import prompt_cache_boundary as boundary
from atlas.agent.prompt_caching import build_prompt_cache_plan, strip_anthropic_cache_control


def setup_function():
    with boundary._lock:
        boundary._prefixes.clear()


def test_longest_registered_prefix_wins_and_requires_nonempty_tail():
    boundary.register_stable_prefix("scaffold")
    boundary.register_stable_prefix("scaffold with details")
    assert boundary.find_stable_prefix("scaffold with details: task") == "scaffold with details"
    assert boundary.find_stable_prefix("scaffold") is None


def test_empty_prefix_is_ignored():
    boundary.register_stable_prefix("")
    assert boundary.find_stable_prefix("volatile") is None


def test_cache_plan_marks_registered_prefix_without_mutating_transcript():
    scaffold = "stable instructions"
    boundary.register_stable_prefix(scaffold)
    transcript = [{"role": "user", "content": scaffold + "\nTask A"}]

    first = build_prompt_cache_plan(transcript, [], static_system_prefix=None)
    second = build_prompt_cache_plan(
        [{"role": "user", "content": scaffold + "\nTask B"}], [],
    )
    assert first.messages[0]["content"][0]["text"] == scaffold
    assert first.messages[0]["content"][0]["cache_control"] == {
        "type": "ephemeral",
    }
    assert first.messages[0]["content"][1]["text"] == "\nTask A"
    assert second.messages[0]["content"][0]["text"] == scaffold
    assert transcript[0]["content"] == scaffold + "\nTask A"
    assert strip_anthropic_cache_control(first.messages)[0]["content"] == transcript[0]["content"]
