"""Cross-conversation activity from the persisted Atlas runtime lifecycle."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


@router.get("/api/conversation-activity")
async def conversation_activity(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Return real run status per conversation and recent lifecycle events.

    A conversation with no recorded run is idle. The event list only contains
    milestones emitted by the runtime; it is suitable for an activity view or
    for a desktop client to notify on newly observed event IDs.
    """
    memory = services.memory
    manager = services.runtime_mgr
    if memory is None or manager is None:
        return {"items": [], "events": []}

    conversations = await memory.list_conversations(limit=None)
    snapshot = await manager.conversation_activity(limit=limit)
    states = {item["conversation_id"]: item for item in snapshot["items"]}
    known_ids = {str(item["id"]) for item in conversations}
    items = []
    for conversation in conversations:
        conversation_id = str(conversation["id"])
        items.append(states.get(conversation_id, {
            "conversation_id": conversation_id,
            "status": "idle",
            "updated_at": conversation.get("updated_at"),
            "waiting_for": None,
        }))
    events = [
        {**event, "event_id": f"{event['run_id']}:{event['sequence']}"}
        for event in snapshot["events"]
        if event["conversation_id"] in known_ids
    ]
    return {"items": items, "events": events}
