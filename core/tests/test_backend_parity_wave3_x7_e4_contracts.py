import pytest

from atlas.engine.tool_registry import _ALIASES, _ALIAS_OUTPUT_DESCRIPTIONS, _alias_output_schema
from atlas.engine.tools.registry import ToolRegistry


@pytest.mark.unit
def test_atlas_aliases_have_tool_specific_output_contracts():
    assert set(_ALIASES) == set(_ALIAS_OUTPUT_DESCRIPTIONS)

    registry = ToolRegistry()
    schemas = {}
    for name in _ALIASES:
        schema = _alias_output_schema(name)
        schemas[name] = schema
        registry.register(
            name=name,
            toolset="atlas-contract-test",
            schema={"name": name, "parameters": {"type": "object"}},
            handler=lambda _args: "ok",
            output_schema=schema,
        )
        assert registry.get_output_contract(name).schema == schema

    assert {schema["title"] for schema in schemas.values()} == {
        f"{name} output" for name in _ALIASES
    }
    assert all(schema.get("description") for schema in schemas.values())
    assert all(schema.get("type") == "string" for name, schema in schemas.items()
               if name != "read_file")
    assert schemas["read_file"]["oneOf"] == [
        {"type": "string"},
        {
            "type": "object",
            "properties": {
                "_multimodal": {"const": True},
                "content": {"type": "array"},
            },
            "required": ["_multimodal", "content"],
            "additionalProperties": True,
        },
    ]
