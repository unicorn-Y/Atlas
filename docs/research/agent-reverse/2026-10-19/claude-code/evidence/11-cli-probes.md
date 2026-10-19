# Isolated binary CLI probes

Executable: extracted native package `claude.exe`, SHA256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`; version resource `2.1.302.0`. Scratch-only profile variables pointed `CLAUDE_CONFIG_DIR`, `APPDATA`, `LOCALAPPDATA`, `HOME`, and `USERPROFILE` at a new empty directory. No authentication status/config, existing home state, prompt, or user project was read. Each command below returned exit 0; output remained in local scratch, with the stated exact first line / excerpt recorded here.

| Command | Lines | Exact observed output |
|---|---:|---|
| `claude.exe --version` | 1 | `2.1.302 (Claude Code)` |
| `claude.exe --help` | 311 | `Usage: claude [options] [command] [prompt]`; `Claude Code - starts an interactive session by default, use -p/--print for non-interactive output` |
| `claude.exe agents --help` | 44 | `Usage: claude agents [options]`; `--json` prints active sessions as a JSON array and does not require a TTY; `--all` includes completed background sessions |
| `claude.exe attach --help` | 3 | `Usage: claude attach <id|name>`; opens a background session in this terminal and leaves it running when returning to shell |
| `claude.exe daemon --help` | 19 | `Usage: claude daemon [subcommand] [options]`; subcommands `run`, `status`, `logs`, `uninstall`, `stop` |
| `claude.exe plugin --help` | 57 | `Usage: claude plugin|plugins [options] [command]`; includes marketplace and plugin lifecycle commands plus `validate` |
| `claude.exe mcp --help` | 46 | `Usage: claude mcp [options] [command]`; includes `serve` to start the Claude Code MCP server |
| `claude.exe logs --help` | 3 | `Usage: claude logs <id|name>` |
| `claude.exe stop --help` | 3 | `Usage: claude stop <id>` |
| `claude.exe respawn --help` | 3 | `Usage: claude respawn <id>|--all` |
| `claude.exe rm --help` | 5 | `Usage: claude rm <id> [--discard-unpushed <commit>@<worktree-id>] [--force-remove-worktree <worktree-id>]` |

No interactive session, model request, service lifecycle command, update/install command, account/profile access, or file-mutating command was run. This is R evidence for CLI/version/help output only, not for agent runtime operation.

