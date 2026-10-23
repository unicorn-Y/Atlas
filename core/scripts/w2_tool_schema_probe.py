"""Probe that schema violations are returned as retryable tool feedback."""
from atlas.kernel.tools import validate_tool_arguments


def main() -> None:
    schema = {"type": "object", "required": ["limit"],
              "properties": {"limit": {"type": "integer", "minimum": 1}},
              "additionalProperties": False}
    assert "missing required" in validate_tool_arguments("fixture", {}, schema)
    assert "must be integer" in validate_tool_arguments("fixture", {"limit": "many"}, schema)
    assert "at least 1" in validate_tool_arguments("fixture", {"limit": 0}, schema)
    assert validate_tool_arguments("fixture", {"limit": 3}, schema) is None
    from atlas.models.router import RouteSpec, _openai_payload
    tool = {"type": "function", "function": {"name": "fixture", "parameters": schema}}
    route = RouteSpec("ollama", "chat_completions", "ollama/test", "http://localhost/v1",
                      capabilities={"supports_tools": False})
    payload = _openai_payload(route, [{"role": "user", "content": "probe"}],
                              {"tools": [tool], "tool_choice": "auto", "parallel_tool_calls": True})
    assert "tools" not in payload and "tool_choice" not in payload and "parallel_tool_calls" not in payload
    print("W2-3 pre-dispatch schema validation and retry guidance: PASS")


if __name__ == "__main__":
    main()
