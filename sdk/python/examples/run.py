from atlas_sdk import Atlas

result = Atlas().run("Return a JSON object with the current task set to 'example'.", output_schema={
    "type": "object", "properties": {"task": {"type": "string"}},
    "required": ["task"], "additionalProperties": False,
})
print(result.structured)
