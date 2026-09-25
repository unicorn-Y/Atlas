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