"""Drive an Atlas session through the versioned stdio app-server protocol."""
from atlas_sdk import AppServer


with AppServer(workspace=".") as app:
    session = app.new_session()
    print(f"session={session.session_id} conversation={session.conversation_id}")
    result = app.prompt(
        session.session_id,
        "Reply with exactly: app-server ready",
        on_event=lambda event: print("event:", event.get("type", "unknown")),
        approve=lambda request: False,
    )
    print(result.text)
    app.close_session(session.session_id)
