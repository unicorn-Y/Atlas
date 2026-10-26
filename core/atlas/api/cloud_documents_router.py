"""Read-only Google Drive and Gmail connector for importing user-selected context."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query

from atlas.api.network_retry import retry_external_request

from atlas.config import DATA_ROOT, load_user_settings, save_user_settings

router = APIRouter()
SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/gmail.readonly"]
_pending: dict[str, dict[str, Any]] = {}
_token_lock = asyncio.Lock()
_auth_progress: dict[str, Any] = {"authorizing": False, "error": ""}
_TOKEN_PATH = DATA_ROOT / "data" / "cloud-connectors" / "google.json"


def _client_id() -> str:
    return str(load_user_settings().get("google_cloud_connector_client_id") or "").strip()


def _read_tokens() -> dict[str, Any]:
    try:
        value = json.loads(_TOKEN_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


async def _write_tokens(value: dict[str, Any]) -> None:
    async with _token_lock:
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = _TOKEN_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(_TOKEN_PATH)
        try:
            os.chmod(_TOKEN_PATH, 0o600)
        except OSError:
            pass


async def _access_token() -> str:
    tokens = _read_tokens()
    access_token = str(tokens.get("access_token") or "")
    if access_token and float(tokens.get("expires_at", 0)) > time.time() + 30:
        return access_token
    refresh_token = str(tokens.get("refresh_token") or "")
    client_id = _client_id()
    if not refresh_token or not client_id:
        raise HTTPException(status_code=401, detail="Google Drive/Gmail 尚未连接，请先完成本机 OAuth 登录。")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await retry_external_request(lambda: client.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }), service="Google OAuth")
    if response.is_error:
        raise HTTPException(status_code=401, detail="Google OAuth 刷新失败；请断开后重新连接。")
    result = response.json()
    tokens.update({"access_token": result["access_token"], "expires_at": time.time() + int(result.get("expires_in", 3600))})
    await _write_tokens(tokens)
    return str(tokens["access_token"])


async def _callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: str) -> None:
    try:
        request = (await asyncio.wait_for(reader.readline(), timeout=5)).decode("latin1")
        target = request.split(" ")[1] if len(request.split(" ")) > 1 else "/"
        query = parse_qs(urlsplit(target).query)
        pending = _pending.get(state)
        code = (query.get("code") or [""])[0]
        error = (query.get("error") or [""])[0]
        returned_state = (query.get("state") or [""])[0]
        if pending and returned_state == state and not pending["future"].done():
            pending["future"].set_result((code, error))
        body = "Google 授权已完成，可以关闭此页面并返回 Atlas。" if code else "Google 授权未完成，可以关闭此页面并返回 Atlas。"
        payload = body.encode("utf-8")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


@router.get("/api/cloud-documents/google/status")
async def google_status() -> dict[str, Any]:
    tokens = _read_tokens()
    return {"configured": bool(_client_id()), "client_id": _client_id(), "connected": bool(tokens.get("refresh_token")),
            "account": str(tokens.get("email") or ""), "authorizing": bool(_auth_progress["authorizing"]),
            "auth_error": str(_auth_progress["error"] or "")}


@router.put("/api/cloud-documents/google/client")
async def google_client(req: dict[str, Any]) -> dict[str, bool]:
    client_id = str(req.get("client_id") or "").strip()
    if len(client_id) > 512 or (client_id and not client_id.endswith(".apps.googleusercontent.com")):
        raise HTTPException(status_code=422, detail="请输入 Google Cloud 中创建的桌面应用 OAuth Client ID。")
    settings = load_user_settings()
    if client_id:
        settings["google_cloud_connector_client_id"] = client_id
    else:
        settings.pop("google_cloud_connector_client_id", None)
    save_user_settings(settings)
    return {"configured": bool(client_id)}


@router.post("/api/cloud-documents/google/authorize")
async def google_authorize() -> dict[str, str]:
    client_id = _client_id()
    if not client_id:
        raise HTTPException(status_code=409, detail="请先保存 Google 桌面应用 OAuth Client ID。")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[str, str]] = loop.create_future()
    server = await asyncio.start_server(lambda reader, writer: _callback(reader, writer, state), "127.0.0.1", port)
    _pending[state] = {"future": future, "server": server, "verifier": verifier, "redirect_uri": redirect_uri}
    _auth_progress.update({"authorizing": True, "error": ""})

    async def finish_auth() -> None:
        try:
            code, error = await asyncio.wait_for(future, timeout=300)
            if error or not code:
                _auth_progress["error"] = "Google 登录未完成或授权被拒绝。"
                return
            async with httpx.AsyncClient(timeout=20) as client:
                response = await retry_external_request(lambda: client.post("https://oauth2.googleapis.com/token", data={
                    "code": code, "client_id": client_id, "redirect_uri": redirect_uri,
                    "code_verifier": verifier, "grant_type": "authorization_code",
                }), service="Google OAuth")
                response.raise_for_status()
                token_data = response.json()
                profile = await retry_external_request(
                    lambda: client.get("https://gmail.googleapis.com/gmail/v1/users/me/profile",
                                       headers={"Authorization": f"Bearer {token_data['access_token']}"}),
                    service="Google Gmail API",
                )
                email = str(profile.json().get("emailAddress") or "") if profile.is_success else ""
            await _write_tokens({"access_token": token_data["access_token"],
                                 "refresh_token": token_data.get("refresh_token") or _read_tokens().get("refresh_token", ""),
                                 "expires_at": time.time() + int(token_data.get("expires_in", 3600)), "email": email})
        except Exception:
            _auth_progress["error"] = "Google OAuth 登录失败；请检查网络、Client ID 和 Google API 配置后重试。"
        finally:
            _auth_progress["authorizing"] = False
            server.close()
            await server.wait_closed()
            _pending.pop(state, None)

    asyncio.create_task(finish_auth(), name="atlas-google-oauth")
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
              "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.delete("/api/cloud-documents/google")
async def disconnect_google() -> dict[str, bool]:
    try:
        _TOKEN_PATH.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法删除本机 Google 授权缓存。") from exc
    return {"connected": False}


@router.get("/api/cloud-documents/google/items")
async def google_items(source: str = Query("drive", pattern="^(drive|gmail)$"),
                       q: str = Query("", max_length=200)) -> dict[str, Any]:
    token = await _access_token()
    async with httpx.AsyncClient(timeout=25, headers={"Authorization": f"Bearer {token}"}) as client:
        if source == "drive":
            query = "trashed = false"
            if q.strip():
                query += " and name contains '" + q.replace("\\", "\\\\").replace("'", "\\'") + "'"
            response = await retry_external_request(lambda: client.get("https://www.googleapis.com/drive/v3/files", params={
                "q": query, "pageSize": 50, "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink,size)",
            }), service="Google Drive API")
            response.raise_for_status()
            return {"source": source, "items": response.json().get("files", [])}
        search = f"{q} " if q.strip() else ""
        response = await retry_external_request(
            lambda: client.get("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                               params={"q": search + "newer_than:1y", "maxResults": 30}),
            service="Google Gmail API",
        )
        response.raise_for_status()
        messages = response.json().get("messages", [])
        items = []
        for message in messages:
            details = await retry_external_request(
                lambda: client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message['id']}",
                                   params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]}),
                service="Google Gmail API",
            )
            details.raise_for_status()
            payload = details.json()
            headers = {header["name"].lower(): header["value"] for header in payload.get("payload", {}).get("headers", [])}
            items.append({"id": message["id"], "name": headers.get("subject") or "(无主题)", "from": headers.get("from", ""), "date": headers.get("date", ""), "snippet": payload.get("snippet", ""), "mimeType": "message/rfc822"})
        return {"source": source, "items": items}


def _gmail_text(payload: dict[str, Any]) -> str:
    body = payload.get("body", {}).get("data")
    if body and payload.get("mimeType") == "text/plain":
        return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8", errors="replace")
    parts = payload.get("parts", [])
    for part in parts:
        text = _gmail_text(part)
        if text:
            return text
    return ""


@router.get("/api/cloud-documents/google/import/{source}/{item_id}")
async def import_google_item(source: str, item_id: str) -> dict[str, str]:
    if source not in {"drive", "gmail"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", item_id):
        raise HTTPException(status_code=422, detail="无效的云端文档引用。")
    token = await _access_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        if source == "drive":
            metadata_response = await retry_external_request(
                lambda: client.get(f"https://www.googleapis.com/drive/v3/files/{item_id}",
                                   params={"fields": "id,name,mimeType,webViewLink"}),
                service="Google Drive API",
            )
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            mime = str(metadata.get("mimeType", ""))
            if mime == "application/vnd.google-apps.document":
                response = await retry_external_request(
                    lambda: client.get(f"https://www.googleapis.com/drive/v3/files/{item_id}/export",
                                       params={"mimeType": "text/plain"}), service="Google Drive API",
                )
            elif mime.startswith("text/") or mime in {"application/json", "application/xml"}:
                response = await retry_external_request(
                    lambda: client.get(f"https://www.googleapis.com/drive/v3/files/{item_id}",
                                       params={"alt": "media"}), service="Google Drive API",
                )
            else:
                raise HTTPException(status_code=415, detail="当前仅支持导入 Google 文档和纯文本文件；不会将二进制内容伪装成文本。")
            response.raise_for_status()
            content = response.content[:200_000].decode("utf-8", errors="replace")
            name = str(metadata.get("name") or "Google Drive 文档")
            url = str(metadata.get("webViewLink") or f"https://drive.google.com/open?id={item_id}")
        else:
            response = await retry_external_request(
                lambda: client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item_id}",
                                   params={"format": "full"}), service="Google Gmail API",
            )
            response.raise_for_status()
            message = response.json()
            headers_list = message.get("payload", {}).get("headers", [])
            headers_by_name = {header["name"].lower(): header["value"] for header in headers_list}
            name = headers_by_name.get("subject") or "Gmail message"
            content = _gmail_text(message.get("payload", {}))[:200_000]
            if not content:
                content = str(message.get("snippet") or "")
            url = f"https://mail.google.com/mail/u/0/#all/{item_id}"
            content = f"Subject: {name}\nFrom: {headers_by_name.get('from', '')}\nDate: {headers_by_name.get('date', '')}\n\n{content}"
    return {"name": name, "content": content, "source_url": url, "source": source}
