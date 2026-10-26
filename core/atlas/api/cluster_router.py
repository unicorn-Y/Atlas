"""Authenticated Atlas-to-Atlas node inventory, task routing and instance controls."""
from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.cluster_control import audit, peer_by_id, read_state, update_peer, write_state

router = APIRouter(tags=["cluster"])
_TOKEN_HEADER = "X-Atlas-Cluster-Token"
_NODE_HEADER = "X-Atlas-Cluster-Node"
_CAPABILITIES = ["sessions.read", "tasks.start", "runs.pause", "runs.resume", "runs.cancel"]
_PUBLIC_PEER_FIELDS = ("id", "name", "url", "created_at", "last_seen", "health", "error", "version", "capabilities")


def _verify(token: str | None) -> dict[str, Any]:
    state = read_state()
    if not token or not secrets.compare_digest(str(token), str(state["service_token"])):
        raise HTTPException(status_code=401, detail="Atlas cluster node authentication failed")
    return state


def _verify_peer(token: str | None, source_node_id: str | None) -> dict[str, Any]:
    state = _verify(token)
    if not source_node_id or not any(item.get("id") == source_node_id for item in state.get("trusted_sources", [])):
        raise HTTPException(status_code=403, detail="This Atlas node has not been paired by the receiving instance")
    return state


def _safe_peer(peer: dict[str, Any]) -> dict[str, Any]:
    return {key: peer.get(key) for key in _PUBLIC_PEER_FIELDS}


async def _peer_get(peer: dict[str, Any], path: str, *, timeout: float = 3.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(peer["url"].rstrip("/") + path,
                                    headers={_TOKEN_HEADER: peer["token"], _NODE_HEADER: read_state()["node_id"]})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("peer returned an invalid response")
        return payload


async def _peer_post(peer: dict[str, Any], path: str, payload: dict[str, Any], *, timeout: float = 8.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(peer["url"].rstrip("/") + path, json=payload,
                                     headers={_TOKEN_HEADER: peer["token"], _NODE_HEADER: read_state()["node_id"]})
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("peer returned an invalid response")
        return value


@router.get("/api/cluster/settings")
async def cluster_settings(request: Request) -> dict[str, Any]:
    """Return the pairing secret only to a loopback desktop client for explicit setup."""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Cluster pairing settings are available only from this machine")
    state = read_state()
    return {"node_id": state["node_id"], "node_name": state["node_name"], "service_token": state["service_token"]}


@router.put("/api/cluster/settings")
async def update_cluster_settings(request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Cluster settings are available only from this machine")
    payload = await request.json()
    name = str(payload.get("node_name") or "").strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=422, detail="Node name must be between 1 and 100 characters")
    state = read_state(); state["node_name"] = name; write_state(state)
    audit("node.rename", subject_id=state["node_id"])
    return {"node_id": state["node_id"], "node_name": name}


@router.post("/api/cluster/token/rotate")
async def rotate_cluster_token(request: Request) -> dict[str, str]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Cluster pairing settings are available only from this machine")
    state = read_state(); state["service_token"] = secrets.token_urlsafe(36); write_state(state)
    audit("node.token.rotate", subject_id=state["node_id"])
    return {"node_id": state["node_id"], "service_token": state["service_token"]}


@router.get("/api/cluster/identity")
async def _cluster_identity_pair(
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
    source_node_id: Annotated[str | None, Header(alias=_NODE_HEADER)] = None,
) -> dict[str, Any]:
    state = _verify(token)
    if source_node_id and source_node_id != state["node_id"]:
        known = {item.get("id") for item in state.setdefault("trusted_sources", [])}
        if source_node_id not in known:
            state["trusted_sources"].append({"id": source_node_id, "paired_at": datetime.now(UTC).isoformat()})
            write_state(state)
            audit("peer.trust.inbound", peer_id=source_node_id)
    from atlas import __version__
    return {"node_id": state["node_id"], "node_name": state["node_name"], "protocol": 1,
            "version": __version__, "capabilities": _CAPABILITIES}


@router.get("/api/cluster/health")
async def cluster_health(
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
    source_node_id: Annotated[str | None, Header(alias=_NODE_HEADER)] = None,
) -> dict[str, Any]:
    state = _verify_peer(token, source_node_id)
    from atlas import __version__
    return {"node_id": state["node_id"], "status": "online", "time": datetime.now(UTC).isoformat(),
            "version": __version__, "capabilities": _CAPABILITIES,
            "components": {"cluster": "ready", "api": "ready"}}


@router.get("/api/cluster/sessions")
async def cluster_sessions(
    services: Annotated[AppServices, Depends(get_app_services)],
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
    source_node_id: Annotated[str | None, Header(alias=_NODE_HEADER)] = None,
) -> dict[str, Any]:
    _verify_peer(token, source_node_id)
    if services.memory is None:
        raise HTTPException(status_code=503, detail="Atlas conversation store is not ready")
    conversations = await services.memory.list_conversations(limit=100)
    runs = {run.conversation_id: run for run in services.runtime_mgr.runs.values()} if services.runtime_mgr else {}
    return {"sessions": [{"id": str(item["id"]), "title": str(item.get("title") or "无标题"),
                          "workspace": str(item.get("workspace") or ""), "updated_at": item.get("updated_at"),
                          "run_id": runs[item["id"]].run_id if item["id"] in runs else "",
                          "status": runs[item["id"]].status if item["id"] in runs else "idle",
                          "waiting_for": runs[item["id"]].waiting_for if item["id"] in runs else None}
                         for item in conversations]}


@router.post("/api/cluster/tasks")
async def cluster_start_task(
    services: Annotated[AppServices, Depends(get_app_services)], request: Request,
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
    source_node_id: Annotated[str | None, Header(alias=_NODE_HEADER)] = None,
) -> dict[str, Any]:
    state = _verify_peer(token, source_node_id)
    payload = await request.json()
    request_id = str(payload.get("request_id") or "")
    if len(request_id) < 8 or len(request_id) > 100:
        raise HTTPException(status_code=422, detail="A stable request_id is required for retry-safe delivery")
    prior = state.get("receipts", {}).get(request_id)
    if prior:
        return {**prior, "duplicate": True}
    content = str(payload.get("content") or "").strip()
    if not content or len(content) > 100_000:
        raise HTTPException(status_code=422, detail="Task content must be between 1 and 100000 characters")
    if services.memory is None or services.runtime_start_handler is None or services.runtime_mgr is None:
        raise HTTPException(status_code=503, detail="Atlas runtime is not ready")
    title = str(payload.get("title") or "来自集群节点的任务").strip()[:120]
    conversation_id = await services.memory.create_conversation(title)
    workspace = payload.get("workspace")
    if isinstance(workspace, str) and workspace:
        await services.memory.update_conversation(conversation_id, workspace=workspace)
    run_id = uuid.uuid4().hex
    try:
        await services.runtime_start_handler(
            f"cluster:{request_id}", {"type": "run.start", "run_id": run_id,
            "conversation_id": conversation_id, "content": content, "workspace": workspace,
            "agent_id": payload.get("agent_id")}, services.runtime_mgr,
        )
    except Exception as exc:
        audit("task.start", peer_id=str(payload.get("source_node_id") or ""), subject_id=run_id,
              result="failed", detail=type(exc).__name__)
        raise HTTPException(status_code=503, detail=f"Remote task could not start: {type(exc).__name__}") from exc
    response = {"conversation_id": conversation_id, "run_id": run_id, "node_id": state["node_id"], "status": "accepted"}
    state = read_state(); receipts = state.setdefault("receipts", {}); receipts[request_id] = response
    if len(receipts) > 1000:
        for key in list(receipts)[:len(receipts) - 1000]: receipts.pop(key, None)
    write_state(state)
    audit("task.start", peer_id=str(payload.get("source_node_id") or ""), subject_id=run_id)
    return response


@router.post("/api/cluster/operations")
async def cluster_operation(
    services: Annotated[AppServices, Depends(get_app_services)], request: Request,
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
    source_node_id: Annotated[str | None, Header(alias=_NODE_HEADER)] = None,
) -> dict[str, Any]:
    _verify_peer(token, source_node_id)
    payload = await request.json(); run_id = str(payload.get("run_id") or ""); action = str(payload.get("action") or "")
    if action not in {"pause", "resume", "cancel"}:
        raise HTTPException(status_code=422, detail="Supported operations are pause, resume, and cancel")
    run = services.runtime_mgr.runs.get(run_id) if services.runtime_mgr else None
    if run is None:
        raise HTTPException(status_code=404, detail="Run is not present on this instance")
    if action == "pause":
        run.pause_event.clear(); run.status = "paused"
        await services.runtime_mgr.send_run(run, run.next_envelope("run.paused", {}), "")
    elif action == "resume":
        run.pause_event.set(); run.status = "running"
        await services.runtime_mgr.send_run(run, run.next_envelope("run.resumed", {}), "")
    else:
        run.cancel_event.set()
        if run.task is not None and not run.task.done():
            run.task.cancel(); await asyncio.gather(run.task, return_exceptions=True)
        run.status = "cancelled"
        if not any(event.get("event") in {"run.completed", "run.failed", "run.cancelled"} for event in run.events):
            await services.runtime_mgr.send_run(run, run.next_envelope("run.cancelled", {}), "")
    await services.runtime_mgr.persist_run(run)
    audit(f"run.{action}", subject_id=run_id)
    return {"run_id": run_id, "status": run.status}


@router.get("/api/cluster/nodes")
async def cluster_nodes(token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None) -> dict[str, Any]:
    state = _verify(token)
    return {"self": {"id": state["node_id"], "name": state["node_name"]},
            "peers": [_safe_peer(item) for item in state["peers"]], "queue": [
                {key: item.get(key) for key in ("id", "peer_id", "title", "created_at", "status", "last_error")}
                for item in state["queue"]]}


@router.post("/api/cluster/nodes")
async def cluster_add_node(request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Peer registration must be initiated on this instance")
    payload = await request.json(); name = str(payload.get("name") or "").strip(); url = str(payload.get("url") or "").strip().rstrip("/")
    peer_token = str(payload.get("token") or "")
    parsed = urlsplit(url)
    if not name or len(name) > 100 or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="Provide a peer name and an http(s) base URL without embedded credentials")
    if len(peer_token) < 24 or len(peer_token) > 256:
        raise HTTPException(status_code=422, detail="Peer token must contain at least 24 characters")
    candidate = {"url": url, "token": peer_token}
    try:
        identity = await _peer_get(candidate, "/api/cluster/identity")
    except (httpx.HTTPError, ValueError) as exc:
        audit("peer.register", result="failed", detail=type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"Peer identity check failed: {type(exc).__name__}") from exc
    if int(identity.get("protocol", 0)) != 1:
        raise HTTPException(status_code=409, detail="Peer cluster protocol is not compatible")
    state = read_state()
    if identity.get("node_id") == state["node_id"]:
        raise HTTPException(status_code=409, detail="This instance cannot be registered as its own peer")
    if any(item.get("id") == identity.get("node_id") for item in state["peers"]):
        raise HTTPException(status_code=409, detail="This peer is already registered")
    peer = {"id": str(identity["node_id"]), "name": name, "url": url, "token": peer_token,
            "version": str(identity.get("version") or "unknown"), "capabilities": identity.get("capabilities", []),
            "created_at": datetime.now(UTC).isoformat(), "last_seen": datetime.now(UTC).isoformat(),
            "health": "online", "error": ""}
    state["peers"].append(peer); write_state(state); audit("peer.register", peer_id=peer["id"])
    return _safe_peer(peer)


@router.delete("/api/cluster/nodes/{peer_id}")
async def cluster_remove_node(peer_id: str, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Peer changes are available only from this instance")
    state = read_state(); before = len(state["peers"])
    peer = next((item for item in state["peers"] if item.get("id") == peer_id), None)
    if peer:
        try:
            await _peer_post(peer, "/api/cluster/revoke", {"source_node_id": state["node_id"]}, timeout=2.0)
        except (httpx.HTTPError, ValueError):
            state["queue"].append({"id": uuid.uuid4().hex, "kind": "revoke", "peer_id": peer_id,
                                   "peer_url": peer["url"], "token": peer["token"],
                                   "source_node_id": state["node_id"], "title": "撤销远端信任", "content": "",
                                   "created_at": datetime.now(UTC).isoformat(), "status": "queued"})
    state["peers"] = [item for item in state["peers"] if item.get("id") != peer_id]
    write_state(state)
    if len(state["peers"]) == before:
        raise HTTPException(status_code=404, detail="Peer not found")
    audit("peer.revoke", peer_id=peer_id)
    return {"removed": True, "peer_id": peer_id}


@router.post("/api/cluster/revoke")
async def cluster_revoke_inbound(
    request: Request,
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
    source_node_id: Annotated[str | None, Header(alias=_NODE_HEADER)] = None,
) -> dict[str, Any]:
    state = _verify(token)
    payload = await request.json()
    if payload.get("source_node_id") != source_node_id:
        raise HTTPException(status_code=422, detail="Revocation node ID does not match the authenticated peer")
    trusted = {item.get("id") for item in state.get("trusted_sources", [])}
    if source_node_id not in trusted:
        if source_node_id in state.get("revoked_sources", []):
            return {"revoked": True, "already_revoked": True, "node_id": source_node_id}
        raise HTTPException(status_code=403, detail="Only the paired source node can revoke its trust")
    state["trusted_sources"] = [item for item in state["trusted_sources"] if item.get("id") != source_node_id]
    state.setdefault("revoked_sources", []).append(str(source_node_id))
    state["revoked_sources"] = state["revoked_sources"][-1000:]
    write_state(state); audit("peer.revoke.inbound", peer_id=str(source_node_id))
    return {"revoked": True, "node_id": source_node_id}


@router.get("/api/cluster/instances")
async def cluster_instances(
    services: Annotated[AppServices, Depends(get_app_services)],
    token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None,
) -> dict[str, Any]:
    state = _verify(token)
    now = datetime.now(UTC).isoformat()
    from atlas import __version__
    local_sessions: list[dict[str, Any]] = []
    if services.memory is not None:
        conversations = await services.memory.list_conversations(limit=100)
        local_runs = {run.conversation_id: run for run in services.runtime_mgr.runs.values()} if services.runtime_mgr else {}
        local_sessions = [{"id": str(item["id"]), "title": str(item.get("title") or "无标题"),
                           "workspace": str(item.get("workspace") or ""), "updated_at": item.get("updated_at"),
                           "run_id": local_runs[item["id"]].run_id if item["id"] in local_runs else "",
                           "status": local_runs[item["id"]].status if item["id"] in local_runs else "idle",
                           "waiting_for": local_runs[item["id"]].waiting_for if item["id"] in local_runs else None}
                          for item in conversations]
    output: list[dict[str, Any]] = [{"id": state["node_id"], "name": state["node_name"], "url": "local",
                                   "health": "online", "last_seen": now, "version": __version__,
                                   "capabilities": _CAPABILITIES, "sessions": local_sessions}]
    for peer in list(state["peers"]):
        try:
            health, sessions = await asyncio.gather(_peer_get(peer, "/api/cluster/health"),
                                                     _peer_get(peer, "/api/cluster/sessions"))
            peer = update_peer(peer["id"], health="online", last_seen=now, error="") or peer
            output.append({**_safe_peer(peer), "health": "online", "last_seen": now,
                           "version": health.get("version", peer.get("version", "unknown")),
                           "capabilities": health.get("capabilities", peer.get("capabilities", [])),
                           "health_detail": health.get("components", {}), "sessions": sessions.get("sessions", [])})
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            peer = update_peer(peer["id"], health="offline", error=type(exc).__name__) or peer
            output.append({**_safe_peer(peer), "health": "offline", "sessions": []})
    await _flush_queue()
    fresh = read_state()
    return {"instances": output, "queue": [{key: item.get(key) for key in ("id", "peer_id", "title", "status", "created_at", "last_error")}
                                            for item in fresh["queue"]]}


@router.post("/api/cluster/nodes/{peer_id}/tasks")
async def cluster_route_task(peer_id: str, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Task routing must be initiated on this instance")
    payload = await request.json(); content = str(payload.get("content") or "").strip()
    if not content or len(content) > 100_000:
        raise HTTPException(status_code=422, detail="Task content must be between 1 and 100000 characters")
    peer = peer_by_id(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer not found")
    request_id = uuid.uuid4().hex
    task = {"request_id": request_id, "source_node_id": read_state()["node_id"],
            "title": str(payload.get("title") or "集群远程任务")[:120], "content": content,
            "workspace": payload.get("workspace"), "agent_id": payload.get("agent_id")}
    try:
        result = await _peer_post(peer, "/api/cluster/tasks", task)
        audit("task.route", peer_id=peer_id, subject_id=str(result.get("run_id") or ""))
        return {**result, "status": "sent", "peer_id": peer_id}
    except (httpx.HTTPError, ValueError) as exc:
        state = read_state(); queued = {"id": request_id, "peer_id": peer_id, "title": task["title"],
                                       "content": content, "workspace": task["workspace"], "agent_id": task["agent_id"],
                                       "request_id": request_id, "source_node_id": task["source_node_id"],
                                       "created_at": datetime.now(UTC).isoformat(), "status": "queued", "last_error": type(exc).__name__}
        state["queue"].append(queued); write_state(state); audit("task.queue", peer_id=peer_id, subject_id=request_id, result="queued", detail=type(exc).__name__)
        return {"status": "queued", "id": request_id, "peer_id": peer_id, "message": "对端离线，任务已写入本机队列，节点恢复后会自动重试。"}


@router.post("/api/cluster/nodes/{peer_id}/runs/{run_id}/{action}")
async def cluster_route_operation(peer_id: str, run_id: str, action: str, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Remote operations must be initiated on this instance")
    peer = peer_by_id(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer not found")
    if action not in {"pause", "resume", "cancel"}:
        raise HTTPException(status_code=422, detail="Unsupported operation")
    try:
        result = await _peer_post(peer, "/api/cluster/operations", {"run_id": run_id, "action": action})
        audit(f"run.{action}", peer_id=peer_id, subject_id=run_id)
        return result
    except (httpx.HTTPError, ValueError) as exc:
        audit(f"run.{action}", peer_id=peer_id, subject_id=run_id, result="failed", detail=type(exc).__name__)
        raise HTTPException(status_code=503, detail=f"Remote operation failed: {type(exc).__name__}") from exc


@router.get("/api/cluster/audit")
async def cluster_audit(token: Annotated[str | None, Header(alias=_TOKEN_HEADER)] = None) -> dict[str, Any]:
    _verify(token)
    return {"events": list(reversed(read_state()["audit"][-250:]))}


async def _flush_queue() -> None:
    state = read_state(); changed = False; dispatched: list[tuple[str, str]] = []
    for item in state["queue"]:
        if item.get("status") != "queued":
            continue
        peer = next((row for row in state["peers"] if row.get("id") == item.get("peer_id")), None)
        if not peer:
            if item.get("kind") == "revoke" and item.get("peer_url") and item.get("token"):
                peer = {"url": item["peer_url"], "token": item["token"]}
            else:
                item["status"] = "failed"; item["last_error"] = "peer_revoked"; changed = True; continue
        if item.get("kind") == "revoke":
            try:
                await _peer_post(peer, "/api/cluster/revoke", {"source_node_id": item["source_node_id"]})
                item["status"] = "sent"; item["last_error"] = ""; changed = True
                dispatched.append((item["peer_id"], item["id"]))
            except (httpx.HTTPError, ValueError) as exc:
                item["last_error"] = type(exc).__name__; item["attempts"] = int(item.get("attempts", 0)) + 1; changed = True
            continue
        payload = {key: item.get(key) for key in ("request_id", "source_node_id", "title", "content", "workspace", "agent_id")}
        try:
            result = await _peer_post(peer, "/api/cluster/tasks", payload)
            item["status"] = "sent"; item["delivered_at"] = datetime.now(UTC).isoformat()
            item["result"] = {key: result.get(key) for key in ("conversation_id", "run_id", "node_id")}
            item["content"] = ""; item["last_error"] = ""; changed = True
            dispatched.append((peer["id"], item["id"]))
        except (httpx.HTTPError, ValueError) as exc:
            item["last_error"] = type(exc).__name__; item["attempts"] = int(item.get("attempts", 0)) + 1; changed = True
    if changed:
        write_state(state)
        for peer_id, task_id in dispatched:
            audit("task.queue.dispatch", peer_id=peer_id, subject_id=task_id)
