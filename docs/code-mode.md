# Atlas code mode

`execute_code` runs a short Python workflow in a separate child process using
the same Python installation as Atlas. The script receives a synchronous
`atlas` bridge with three entry points:

- `atlas.list_tools()` returns the schemas exposed to this run, including
  locally registered, computer, web, MCP, and kernel edit tools when available.
- `atlas.call_tool(name, arguments)` calls an enabled Atlas runtime tool and
  returns its normal result envelope. Calls run in script order.
- `atlas.workspace` is the disposable working directory assigned to this run.

The child process starts with that directory as its current directory. Local
tool calls that omit `cwd` use the same directory. Explicit paths and tool
calls continue through the existing Atlas runtime configuration and tool
execution pipeline, including its normal run policy and event handling. The bridge
records each call's tool name, order, status, and result type (without tool
arguments or result values), then streams progress while the script runs. The final result also includes stdout,
stderr, the script's `result` value, and the step log.
Set `dry_run=true` to parse the script and preview statically named tool calls;
the preview does not execute Python. Dynamically computed tool names appear as
`<dynamic>`.

Each invocation receives a new operating-system temporary directory named
`atlas-code-mode-*`; Atlas removes it after success, script error, timeout, or
cancellation. This is separate from the task Docker sandbox. Execution uses
Atlas's configured Python dependencies and existing tool permissions. The
default time limit is 30 seconds (runtime maximum 120 seconds). Captured stdout
and stderr are returned with bounded tails (16,000 and 8,000 characters).

Example:

```python
results = []
for path in ("a.py", "b.py"):
    results.append(atlas.call_tool("local_file", {"action": "stat", "path": path}))
result = {"workspace": atlas.workspace, "files": results}
```
