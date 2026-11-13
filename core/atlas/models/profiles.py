"""Per-family model profiles: how Atlas feeds and supervises each kind of model.

One place to tune a model family. Matching is by substring on the model id or the
wire model (``deepseek/deepseek-v4.1-flash``). Fields:

- ``guidance``: short behavior notes appended to the system prompt.
- ``stuck``: StuckDetector thresholds; weaker tool-callers get tighter ones.
- ``max_output_tokens``: fallback only, used when the model's own config sets none.

DeepSeek notes come from the FEEL-1 log scan (docs/plan/FEEL-1.md): one tool call per
turn, whole-file rewrites, inline code through the shell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelProfile:
    family: str
    markers: tuple[str, ...]
    guidance: tuple[str, ...]
    stuck: dict[str, int] = field(default_factory=dict)
    max_output_tokens: int | None = None


_COMMON = (
    "Independent reads and searches go in one response; they run in parallel.",
)

PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        "Claude", ("claude", "anthropic"),
        ("Use exact surrounding text when editing; ask for clarification when the target is ambiguous.",),
    ),
    ModelProfile(
        "GPT/Codex", ("gpt", "codex", "openai"),
        ("Keep tool arguments valid JSON and wait for tool results before continuing.",),
    ),
    ModelProfile(
        "Gemini", ("gemini",),
        ("Keep each tool request focused and use returned file context before editing.",
         "Don't call the same tool again with the same arguments; use the result you already have."),
    ),
    ModelProfile(
        "DeepSeek", ("deepseek",),
        ("Change existing files with edit, in small targeted pieces; don't rewrite a whole file with write.",
         "Write multi-line scripts to a file and run the file; don't put code inside a shell command.",
         "Keep each tool call's arguments short; split large content across several calls.",
         "After an edit, read the changed lines back before reporting the work as done.",
         "If a tool fails the same way twice, change approach instead of retrying it unchanged."),
        stuck={"action_observation": 3, "action_error": 2},
        max_output_tokens=8192,
    ),
    ModelProfile(
        "Kimi", ("kimi", "moonshot"),
        ("Use short, focused edits and enough context to identify one target.",),
    ),
    ModelProfile(
        "GLM", ("glm", "zhipu", "zai/"),
        ("Use the registered tool names and include required arguments explicitly.",),
    ),
    ModelProfile(
        "Qwen", ("qwen",),
        ("Keep file paths and requested ranges explicit in file operations.",),
    ),
    ModelProfile(
        "MiniMax", ("minimax",),
        ("Wait for tool results before giving a final answer.",),
    ),
)

DEFAULT = ModelProfile("Default", (), ("Follow the tool descriptions and verify edits before finishing.",))


def profile_for(*models: Any) -> ModelProfile:
    """First profile whose marker appears in any of the given model names."""
    # A generic LiteLLM provider prefix (for example ``openai/``) must not
    # classify a DeepSeek wire model as GPT before its model family is checked.
    names = [str(item or "").lower().rsplit("/", 1)[-1] for item in models if item]
    for name in names:
        for profile in PROFILES:
            if any(marker in name for marker in profile.markers):
                return profile
    return DEFAULT


def guidance_text(*models: Any) -> str:
    profile = profile_for(*models)
    notes = (*profile.guidance, *_COMMON)
    return f"{profile.family}:\n" + "\n".join(f"- {note}" for note in notes)
