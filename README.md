# Atlas

All-in-one AI Personal Assistant. Local-first, model-agnostic, fully extensible.

## Quick Start

For a Windows source checkout, install Git, Node.js 22.12 or newer and Python 3.14,
then double-click `start-atlas.bat`. On first launch it prepares a project-local
Python environment, clones the pinned Hermes engine next to the repository
(`..\hermes-agent`) and installs the desktop dependencies. Every launch keeps that
Hermes checkout at the commit pinned in `core/pyproject.toml`.

For end users, use the Windows installer; it includes the backend runtime and
does not require Python to be installed on the target machine.

Before sending a message, open **Settings** and enter an OpenAI-compatible API
base URL and API key. Atlas stores these settings locally under the app data
directory for installed builds, or in the local development data directory.
The key is never part of the release package.

```bash
# Alternative: run the development desktop workflow from a terminal
npm ci
py -3.14 -m venv core/.venv
core/.venv/Scripts/python.exe core/scripts/setup_hermes.py
core/.venv/Scripts/python.exe -m pip install -e core
npm run dev
```

Hermes is not a pip dependency: the fork refuses wheel builds, so
`core/scripts/setup_hermes.py` installs an editable checkout of the commit in
`[tool.atlas.hermes]`. It enables Git long paths for that checkout (Hermes has deeply
nested docs) and refuses to touch a checkout with uncommitted changes.
`atlas doctor` reports when the installed Hermes is not at the pin.

## Windows Desktop Build

The Windows installer is written to `frontend/windows-release/Atlas-<version>-Setup.exe`.
It creates a desktop/start-menu entry and includes the backend runtime. Build it
from Windows with Node.js 22.12 or newer and Python 3.14 (with Hermes set up as above):

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
├── core/                 # Python backend
│   ├── atlas/
│   │   ├── engine/       # Hermes runtime adapter (agent loop, tools, MCP registration)
│   │   ├── agent/        # Atlas run orchestration around the Hermes turn
│   │   ├── api/          # FastAPI routers (server.py only builds the app)
│   │   ├── models/       # Model catalog and the shared model router
│   │   ├── memory/       # SQLite memory and conversation metadata
│   │   ├── channels/     # Telegram / Slack / Feishu / DingTalk / WeCom / email / webhook
│   │   ├── tools/        # MCP client, computer/browser runtimes, web tools
│   │   └── cli.py        # `atlas run` (headless) and `atlas doctor`
│   ├── scripts/setup_hermes.py
│   ├── pyproject.toml    # [tool.atlas.hermes] pins the Hermes fork commit
│   └── tests/
├── frontend/             # Electron + React desktop app
├── skills/               # Bundled skills
├── config/               # atlas.example.toml
└── docs/plan/            # DATA-OWNERS, VENDORED, EXECUTION-GUIDE
```
