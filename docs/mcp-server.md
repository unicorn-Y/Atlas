# Atlas MCP server

Atlas can expose its local capabilities to MCP clients over standard input and
standard output. This is the same server Atlas already uses for local agent
integrations.

## Connect a client

Run `atlas mcp serve` as the MCP client's stdio server command. For example, in
an MCP client configuration that supports command-based stdio servers:

```json
{
  "mcpServers": {
    "atlas": {
      "command": "atlas",
      "args": ["mcp", "serve"]
    }
  }
}
```

The client must be able to find the same Atlas installation and configuration
as the `atlas` command used in a terminal. Atlas keeps protocol messages on
stdout and sends diagnostics to stderr.

## Exposed tools and resources

The server registers Atlas local execution tools, computer-use tools, structural
code search (`coding_ast_grep`), and repository maps (`coding_repo_map`). Tool
schemas are published through MCP `tools/list`. The read-only
`atlas://capabilities` resource reports the server version, transport, and
available tool names. Resource support can be inspected with MCP
`resources/list` and `resources/read`.

Tool calls use Atlas's existing local runtimes. They execute as the operating
system user running Atlas, with the same filesystem, process, Git, and computer
operation behavior as Atlas's local tools. Atlas does not add a second approval
or allowlist layer to this MCP bridge. Credentials stay in the local Atlas
configuration and are not included in tool results or the capability resource.

## Authentication and transport boundary

This command supports stdio only and does not listen on a network port. The MCP
client starts the server process and communicates through its pipes; access to
those pipes is controlled by the operating system and the client process. Run
the client and Atlas under the intended user account. Any process that can
control the launched server's stdio can invoke the same local capabilities.
Network clients must use a separate authenticated gateway; this command does
not expose an unauthenticated HTTP endpoint.

## Troubleshooting

- Check that `atlas mcp serve` works in the same environment as the MCP client.
- Keep stdout reserved for the MCP protocol. Atlas sends logs to stderr.
- If the client cannot find a tool, refresh its MCP connection and inspect its
  `tools/list` result.
