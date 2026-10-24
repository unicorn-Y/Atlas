# Atlas Python SDK

Install from the repository root with `pip install -e sdk/python`. The `atlas` CLI must be on `PATH`.

```python
from atlas_sdk import Atlas

result = Atlas().run("Reply with a JSON object containing ok=true.", output_schema={
    "type": "object", "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"], "additionalProperties": False,
})
print(result.structured)
```

`Atlas.stream(prompt, cwd=...)` yields JSONL event dictionaries. Save `result.session_id` and pass it to
`Atlas.resume(session_id, prompt)` to continue that conversation.

See [`examples/run.py`](examples/run.py) and [`examples/stream.py`](examples/stream.py).
