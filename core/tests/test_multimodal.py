"""Focused checks for transient image input validation and serialization."""

import base64

import pytest
from langchain_core.messages import HumanMessage

from atlas.agent import AgentOrchestrator
from atlas.server import _validated_image_attachments


def _data_url(content_type: str, payload: bytes = b"image") -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def test_accepts_supported_inline_image() -> None:
    image = _data_url("image/png")
    assert _validated_image_attachments([image]) == [image]


@pytest.mark.parametrize("value", ["https://example.test/image.png", _data_url("image/svg+xml")])
def test_rejects_remote_or_unsupported_image(value: str) -> None:
    with pytest.raises(ValueError):
        _validated_image_attachments([value])


def test_rejects_more_than_four_images() -> None:
    with pytest.raises(ValueError, match="at most four"):
        _validated_image_attachments([_data_url("image/png")] * 5)


def test_multimodal_human_message_keeps_text_and_image_url() -> None:
    image = _data_url("image/webp")
    content = AgentOrchestrator._multimodal_content("What is in this picture?", [image])
    message = HumanMessage(content=content)
    converted = AgentOrchestrator._to_litellm_messages([message])
    assert converted == [{"role": "user", "content": content}]
    assert content[0]["text"] == "What is in this picture?"
    assert content[1]["image_url"] == {"url": image}
