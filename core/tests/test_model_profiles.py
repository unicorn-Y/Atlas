"""The selected model id must take precedence over a generic wire provider prefix."""

import pytest

from atlas.models.profiles import profile_for

pytestmark = pytest.mark.unit


def test_deepseek_wire_model_uses_deepseek_output_profile():
    profile = profile_for("openai/deepseek-v4.1-flash", "deepseek-v4.1-flash")

    assert profile.family == "DeepSeek"
    assert profile.max_output_tokens == 8192
