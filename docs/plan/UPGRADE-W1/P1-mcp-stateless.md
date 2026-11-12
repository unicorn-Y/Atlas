# P1 — MCP stateless protocol adaptation

## Changes

- core/atlas/tools/mcp_client.py:330 defaults URL servers to streamable_http; stdio remains stdio and configured SSE remains available.
- core/atlas/tools/mcp_client.py:585 treats missing/failed initialize as stateless fallback for Streamable HTTP, uses SDK discover() when supported, then lists tools. The HTTP client sets MCP-Protocol-Version and reads MCP-Tool-Cache response hints (:738–787). Runtime state reports connected or connected_stateless (:643). Existing access rules, redaction, cooldown, and monitoring logic were not intentionally changed.
- core/tests/fixtures/stateless_mcp_server.py:1 adds a real stateless Streamable HTTP fixture; core/tests/test_mcp_stateless_handshake.py:14 verifies list-tools and one tool call.

## Why

This adds an HTTP path for servers that do not complete the stateful initialize handshake while preserving explicit SSE configuration and the existing MCP policies.

## Verification

Command (required interpreter, PYTHONPATH=D:\Atlas\core, cwd D:\Atlas):

    $env:PYTHONPATH='D:\Atlas\core'; & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest core/tests/test_mcp_stateless_handshake.py --basetemp=core/.pytest-basetemp-mcp-handshake-final -q
    1 passed, 6 warnings in 6.33s

Existing MCP client regression:

    $env:PYTHONPATH='D:\Atlas\core'; & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest core/tests/test_mcp_client.py --basetemp=core/.pytest-basetemp-mcp-client-final -q
    4 failed, 18 passed, 7 warnings in 6.65s

The failures were test_node_release_manifest_pins_official_binary_and_sha256, test_start_records_runtime_config_discovery_and_restart_state, test_failed_configured_server_blocks_mcp_runtime_without_echoing_arguments, and test_connect_discovers_tools_for_agent. Therefore the old SSE server regression is not established as passing.

Required broad command:

    $env:PYTHONPATH='D:\Atlas\core'; & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest core/tests -k mcp --basetemp=core/.pytest-basetemp-mcp-final -q
    Interrupted during collection: 2410 deselected, 2 errors

Collection errors are test_hermes_setup.py (missing atlas.hermes_pin) and test_local_models_adapter.py (missing ATLAS_PROBE_NONCE). No tests ran in that invocation.

## Acceptance evidence and remaining work

- Passed: real stateless Streamable HTTP server discovery and a ping tool call.
- Unverified: SSE regression due to four failures in the MCP client file; broad MCP suite is blocked at collection.
- SDK HTTP response headers were read using an httpx response hook installed in the allowed client file; the fixture does not assert the TTL cache behavior.
- During execution two empty commits appeared on ui-redesign (9c5255bf, 578cb08d, both authored as Atlas <atlas@localhost>); neither the main agent nor workers report invoking git commit. Their tree matched origin/ui-redesign, so the branch pointer was restored with git reset --mixed origin/ui-redesign; the working tree was retained. No commit remains on the branch.
