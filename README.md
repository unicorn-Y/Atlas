# Atlas

All-in-one AI Personal Assistant. Local-first, model-agnostic, fully extensible.

## Quick Start

For a Windows source checkout, install Node.js 22.12 or newer and Python 3.10 or
newer, then double-click `start-atlas.bat`. On first launch it prepares a
project-local Python environment and installs the desktop dependencies. Later
launches open the Electron desktop app directly.

For end users, use the Windows installer; it includes the backend runtime and
does not require Python to be installed on the target machine.

Before sending a message, open **Settings** and enter an OpenAI-compatible API
base URL and API key. Atlas stores these settings locally under the app data
directory for installed builds, or in the local development data directory.
The key is never part of the release package.

```bash
# Alternative: run the development desktop workflow from a terminal
npm ci
py -3 -m venv core/.venv
core/.venv/Scripts/python.exe -m pip install -e core
npm run dev
```

## Windows Desktop Build

The Windows installer is written to `frontend/windows-release/Atlas-<version>-Setup.exe`.
It creates a desktop/start-menu entry and includes the backend runtime. Build it
from Windows with Node.js 22.12 or newer and Python 3.10 or newer:

```powershell
npm ci
npm --prefix frontend run dist:win
```

The build command starts from clean packaging outputs, bundles the backend,
verifies and stages the pinned official Node 22.23.3 archive, and places the
installer plus `release-manifest.json` in `frontend/windows-release`. To use an
already downloaded archive as a cache input, set `ATLAS_NODE_ARCHIVE` to its
path before running the build; its SHA-256 must still match
`frontend/node-runtime.json`. Python is a build-time prerequisite only.

Atlas stores its installed-app configuration, settings, and database under Electron's per-user application data directory. Development runs continue to use the repository's `config/` and `data/` directories.

The example config binds the API to `127.0.0.1`. MCP tools are optional and may
need Node.js, network access, or provider credentials. The filesystem server
uses the current user's `Documents` folder by default and downloads its MCP
package on first launch. Keep `config/atlas.toml`, user settings, and real API
keys out of release artifacts and source control.

## Project Structure

```
Atlas/
├── core/               # Python backend (Agent, Memory, Model Manager)
│   ├── atlas/
│   │   ├── agent/      # LangGraph orchestrator
│   │   ├── memory/     # SQLite + FTS5 memory system
│   │   ├── models/     # LiteLLM model manager
│   │   ├── tools/      # MCP tool integrations
│   │   └── server.py   # FastAPI + WebSocket server
│   ├── pyproject.toml
│   └── tests/
├── frontend/           # Electron + React UI
│   ├── src/
│   │   ├── main/       # Electron main process
│   │   ├── renderer/   # React renderer
│   │   └── shared/     # Shared types
│   └── package.json
├── skills/             # Skill library (migrated from Hermes)
├── config/             # Configuration files
│   └── atlas.toml
├── data/               # Local data (SQLite, logs)
├── package.json
└── ecosystem.config.js # PM2 process config
```
