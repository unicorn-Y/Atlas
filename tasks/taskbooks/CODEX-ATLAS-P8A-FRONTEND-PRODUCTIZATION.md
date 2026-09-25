# CODEX-ATLAS-P8A-FRONTEND-PRODUCTIZATION

## Goal
Transform Atlas frontend from developer preview into a usable personal agent interface.

## Scope

### 1. Markdown Rendering
- Render assistant markdown output.
- Support code blocks and basic formatting.

### 2. Conversation Management
- Implement real new conversation flow.
- Connect conversation creation with backend state.

### 3. Settings Foundation
- Add settings page framework.
- Prepare API/model configuration entry points.

### 4. Frontend Architecture
- Split large App components into maintainable modules.
- Keep existing runtime protocols unchanged.

### 5. Remove Product Mock Data
- Replace hardcoded user/workspace/demo states with real state sources.

## Out of Scope
- MemoryOS integration.
- Planner/multi-agent system.
- Voice/video.
- MCP redesign.
- Runtime protocol redesign.

## Acceptance
- Existing runtime tests remain passing.
- Frontend build passes.
- New frontend flows have tests where applicable.
