from types import SimpleNamespace

from atlas.engine.atlas_runtime import _model_family_guidance
from atlas.engine.tool_registry import _append_repetition_reminder
from atlas.engine.tool_registry import _multimodal_image_result


def test_repeated_same_file_edits_append_a_short_reminder():
    runtime = SimpleNamespace(file_edit_counts={})
    args = {"path": "src/example.py"}

    results = [
        _append_repetition_reminder(runtime, "patch", args, "已修改。", threshold=2)
        for _ in range(2)
    ]

    assert results[0] == "已修改。"
    assert results[1].startswith("已修改。\n\n提醒：")


def test_repetition_reminder_is_scoped_to_file_and_run():
    first_run = SimpleNamespace(file_edit_counts={})
    second_run = SimpleNamespace(file_edit_counts={})

    for _ in range(2):
        _append_repetition_reminder(first_run, "write_file", {"path": "a.py"}, "ok", threshold=2)
    other_file = _append_repetition_reminder(first_run, "patch", {"path": "b.py"}, "ok", threshold=2)
    new_run = _append_repetition_reminder(second_run, "patch", {"path": "a.py"}, "ok", threshold=2)

    assert other_file == "ok"
    assert new_run == "ok"


def test_model_family_guidance_is_short_and_specific():
    models = {
        "anthropic/claude-sonnet": "claude",
        "openai/gpt-5": "gpt",
        "gemini-3.8-pro": "gemini",
        "deepseek-chat": "deepseek",
        "moonshot/kimi-k2": "kimi",
        "zai/glm-5": "glm",
        "qwen3-coder": "qwen",
        "minimax-m2": "minimax",
        "other-model": "default",
    }
    for model, family in models.items():
        guidance = _model_family_guidance(model)
        assert guidance
        assert family == "default" or family in guidance.lower()
        # Profiles (atlas.models.profiles) carry a few notes per family, still kept brief.
        assert len(guidance) < 800


def test_image_tool_result_keeps_thumbnail_data_and_text_summary():
    result = _multimodal_image_result("data:image/png;base64,AA==", "sample.png")

    assert result["_multimodal"] is True
    assert result["content"][0]["type"] == "text"
    assert result["content"][1]["image_url"]["url"] == "data:image/png;base64,AA=="
    assert "sample.png" in result["text_summary"]
