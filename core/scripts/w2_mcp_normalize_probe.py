"""Probe MCP content normalization and the shared output budget truncator."""
from types import SimpleNamespace

from atlas.tools.mcp_client import _budget_mcp_content, normalize_mcp_content
from atlas.tools.output_truncate import truncate_head_tail


def main() -> None:
    text = normalize_mcp_content(SimpleNamespace(text="hello"))
    image = normalize_mcp_content(SimpleNamespace(data=b"png", mimeType="image/png"))
    link = normalize_mcp_content(SimpleNamespace(uri="file:///a", name="a.txt", title="A"))
    assert text == {"type": "text", "text": "hello"}
    assert image["type"] == "image_url" and image["image_url"]["url"].startswith("data:image/png;base64,")
    assert link["type"] == "resource_link" and link["uri"] == "file:///a"
    resource, _remaining = _budget_mcp_content({"type": "resource", "uri": "file:///large",
        "contents": [text]}, 3)
    assert "MCP OUTPUT TRUNCATED" in resource["contents"][0]["text"]
    omitted, remaining = _budget_mcp_content(image, 2)
    assert omitted["type"] == "text" and "omitted" in omitted["text"] and remaining == 0
    clipped = truncate_head_tail("head" + "x" * 1000 + "tail", 80, label="MCP OUTPUT")
    assert "MCP OUTPUT TRUNCATED" in clipped and clipped.startswith("head") and clipped.endswith("tail")
    print("W2-9 MCP text/image/resource normalization and budget clipping: PASS")


if __name__ == "__main__":
    main()
