# IDE terminal context

`atlas chat` and `atlas exec` look for editor context when launched from an IDE
terminal. Atlas attaches the workspace and active file to the first chat request
or one-shot run. A selected range is included when the IDE supplies it. Run
`atlas ide context` to inspect the context Atlas will detect; add `--json` for a
script-friendly result.

## VS Code and Cursor

When Atlas IDE Bridge is installed and connected, Atlas reads the live active
file, selection, language, and workspace over its authenticated localhost
connection. No extension is required for the workspace fallback. To pass active
editor values without the extension, add these variables to
`terminal.integrated.env.windows` (or the matching `linux` / `osx` setting) in
VS Code settings:

```json
{
  "terminal.integrated.env.windows": {
    "ATLAS_IDE_FILE": "${file}",
    "ATLAS_IDE_SELECTION": "${selectedText}",
    "ATLAS_IDE_WORKSPACE": "${workspaceFolder}"
  }
}
```

Open a new integrated terminal after changing the setting. VS Code supports
predefined variables such as `${file}`, `${selectedText}`, and
`${workspaceFolder}` in terminal environment settings. If an empty editor has no
active file, Atlas uses the terminal's working directory.

## Zed

For Zed tasks, pass the active file and worktree variables through the task
environment, then launch Atlas from that task:

```json
[
  {
    "label": "Atlas chat",
    "command": "atlas",
    "args": ["chat"],
    "env": {
      "ZED_WORKTREE_ROOT": "${ZED_WORKTREE_ROOT}",
      "ZED_RELATIVE_FILE": "${ZED_RELATIVE_FILE}"
    }
  }
]
```

Zed documents `ZED_RELATIVE_FILE` relative to `ZED_WORKTREE_ROOT` for tasks. To
include a selection, set `ATLAS_IDE_SELECTION` in the task environment to the
selected text supplied by your task or shell integration.

## JetBrains and other terminals

Configure `ATLAS_IDE_WORKSPACE`, `ATLAS_IDE_FILE`, and optionally
`ATLAS_IDE_SELECTION` in the IDE terminal environment. Atlas also recognizes
JetBrains terminal markers and uses `IDEA_INITIAL_DIRECTORY` as the workspace
when present. In any terminal, the fallback is the current working directory.

The fallback reads environment values only; it does not inspect editor windows
or read the active file. It attaches the file path so the agent can use its
existing workspace tools when needed. Selection text is bounded to 32,000
characters. VS Code Bridge context includes the current selection directly.

References: [VS Code predefined variables](https://code.visualstudio.com/docs/reference/variables-reference),
[VS Code terminal settings](https://code.visualstudio.com/docs/terminal/appearance),
[Zed task environment variables](https://zed.dev/docs/tasks).
