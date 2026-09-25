# Atlas

All-in-one AI Personal Assistant. Local-first, model-agnostic, fully extensible.

## Quick Start

```bash
# Backend
cd core
pip install -e .
uvicorn atlas.server:app --reload --port 8765

# Frontend
cd frontend
npm install
npm run dev
```

## Windows Desktop Build

The Windows installer is written to `frontend/windows-release/Atlas-<version>-Setup.exe`:

```powershell
npm install
npm run dist:win
```

The installer includes the Electron application, Atlas backend source, skills, and example configuration. The backend currently runs with the system Python installation, so prepare its dependencies once before launching Atlas:

```powershell
py -3 -m pip install -e .\core
```

Atlas stores its installed-app configuration, settings, and database under Electron's per-user application data directory. Development runs continue to use the repository's `config/` and `data/` directories.

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
