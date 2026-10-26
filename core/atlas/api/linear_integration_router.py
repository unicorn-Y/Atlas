"""Local Linear integration backed by a personal API key in the OS keyring.

The router intentionally exposes only the operations used by the Settings
panel: verify the key and list teams, create an issue, and add an issue comment.
All GraphQL writes require an explicit API request from the UI; this module
does not schedule or automatically submit anything to Linear.
"""

from __future__ import annotations

import re
from typing import Any, NoReturn

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/integrations/linear", tags=["linear"])

GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"
KEYRING_SERVICE = "Atlas"
KEYRING_ACCOUNT = "atlas.integration.linear.api_key"
SECRET_NAME = "ATLAS_LINEAR_API_KEY"
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

_IDENTITY_TEAMS_QUERY = """
query AtlasLinearIdentity {
  viewer { id name email }
  teams { nodes { id name } }
}
"""

_ISSUE_CREATE_MUTATION = """
mutation AtlasLinearIssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id title }
  }
}
"""

_COMMENT_CREATE_MUTATION = """
mutation AtlasLinearCommentCreate($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment { id body }
  }
}
"""


class LinearIssuePayload(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=30_000)
    team_id: str = Field(min_length=1, max_length=128)


class LinearCommentPayload(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)


class LinearAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _credential_store() -> Any:
    from atlas import secrets_store
    value = secrets_store.resolve_secret(SECRET_NAME)
    if value:
        return value
    # One-time migration from the prior dedicated keyring slot.
    try:
        import keyring
        legacy = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        legacy = None
    if legacy:
        secrets_store.set_secret(SECRET_NAME, legacy, "Linear connector API key")
        return legacy
    return None


def _store_credential(value: str) -> None:
    try:
        from atlas import secrets_store
        secrets_store.set_secret(SECRET_NAME, value, "Linear connector API key")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="系统凭据库写入失败；Linear API key 未保存。") from exc


def _delete_credential() -> None:
    try:
        from atlas import secrets_store
        secrets_store.delete_secret(SECRET_NAME)
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=503, detail="系统凭据库删除失败。") from exc


def _safe_message(value: Any, secret: str) -> str:
    message = str(value or "Linear API 请求失败").strip()
    if secret:
        message = message.replace(secret, "[redacted]")
    return message[:500] or "Linear API 请求失败"


async def _graphql(token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send one fixed-host GraphQL request and reject HTTP or GraphQL errors."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
            response = await client.post(
                GRAPHQL_ENDPOINT,
                headers={"Authorization": token, "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}},
            )
    except httpx.TimeoutException as exc:
        raise LinearAPIError(504, "Linear API 请求超时。") from exc
    except httpx.RequestError as exc:
        raise LinearAPIError(502, "无法连接 Linear API。") from exc

    if not response.is_success:
        status = response.status_code
        if status in (401, 403):
            detail = "Linear API key 无效或权限不足。"
        elif status == 429:
            detail = "Linear API 请求过于频繁，请稍后重试。"
        else:
            detail = f"Linear API 返回 HTTP {status}。"
        raise LinearAPIError(502, detail)

    try:
        payload = response.json()
    except ValueError as exc:
        raise LinearAPIError(502, "Linear API 返回了无效 JSON。") from exc
    if not isinstance(payload, dict):
        raise LinearAPIError(502, "Linear API 返回了无效 GraphQL 响应。")

    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        messages = [
            _safe_message(item.get("message") if isinstance(item, dict) else item, token)
            for item in errors[:3]
        ]
        raise LinearAPIError(502, "; ".join(messages))

    data = payload.get("data")
    if not isinstance(data, dict):
        raise LinearAPIError(502, "Linear API 响应缺少 GraphQL data。")
    return data


def _identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    viewer = data.get("viewer")
    teams_connection = data.get("teams")
    nodes = teams_connection.get("nodes") if isinstance(teams_connection, dict) else None
    if not isinstance(viewer, dict) or not isinstance(nodes, list):
        raise LinearAPIError(502, "Linear API 未返回 viewer 或 teams。")
    teams = [
        {"id": item["id"], "name": item["name"]}
        for item in nodes
        if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("name"), str)
    ]
    return {
        "configured": True,
        "connected": True,
        "viewer": {
            "id": str(viewer.get("id") or ""),
            "name": str(viewer.get("name") or ""),
            "email": str(viewer.get("email") or ""),
        },
        "teams": teams,
        "error": None,
    }


async def _verified_status(token: str) -> dict[str, Any]:
    return _identity_payload(await _graphql(token, _IDENTITY_TEAMS_QUERY))


def _saved_token() -> str:
    token = _credential_store()
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(status_code=409, detail="尚未连接 Linear，请先保存并验证个人 API key。")
    return token.strip()


def _raise_linear_error(exc: LinearAPIError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/status")
async def linear_status() -> dict[str, Any]:
    token = _credential_store()
    if not isinstance(token, str) or not token.strip():
        return {"configured": False, "connected": False, "viewer": None, "teams": [], "error": None}
    token = token.strip()
    try:
        return await _verified_status(token)
    except LinearAPIError as exc:
        return {
            "configured": True,
            "connected": False,
            "viewer": None,
            "teams": [],
            "error": _safe_message(exc.detail, token),
        }


@router.put("/credential")
async def save_linear_credential(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="请求必须包含 JSON 格式的 API key。") from exc
    raw_token = payload.get("api_key") if isinstance(payload, dict) else None
    if not isinstance(raw_token, str):
        raise HTTPException(status_code=422, detail="Linear API key 必须是字符串。")
    token = raw_token.strip()
    if not token or len(token) > 1024:
        raise HTTPException(status_code=422, detail="Linear API key 长度无效。")
    try:
        status = await _verified_status(token)
    except LinearAPIError as exc:
        _raise_linear_error(exc)
    _store_credential(token)
    return status


@router.delete("/credential")
async def clear_linear_credential() -> dict[str, bool]:
    _delete_credential()
    return {"ok": True, "configured": False}


@router.post("/issues")
async def create_linear_issue(payload: LinearIssuePayload) -> dict[str, Any]:
    token = _saved_token()
    title = payload.title.strip()
    team_id = payload.team_id.strip()
    if not title or not team_id:
        raise HTTPException(status_code=422, detail="标题和团队不能为空。")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", team_id):
        raise HTTPException(status_code=422, detail="Linear team ID 格式无效。")

    try:
        identity = await _verified_status(token)
        if team_id not in {team["id"] for team in identity["teams"]}:
            raise HTTPException(status_code=422, detail="所选团队不在当前 Linear 账号可访问的团队列表中。")
        data = await _graphql(token, _ISSUE_CREATE_MUTATION, {"input": {
            "title": title,
            "description": payload.description.strip(),
            "teamId": team_id,
        }})
    except LinearAPIError as exc:
        _raise_linear_error(exc)

    result = data.get("issueCreate")
    issue = result.get("issue") if isinstance(result, dict) else None
    if not isinstance(result, dict) or result.get("success") is not True or not isinstance(issue, dict):
        raise HTTPException(status_code=502, detail="Linear 未确认 issue 创建成功。")
    return {"id": str(issue.get("id") or ""), "title": str(issue.get("title") or title)}


@router.post("/issues/{issue_id}/comments")
async def create_linear_comment(issue_id: str, payload: LinearCommentPayload) -> dict[str, Any]:
    token = _saved_token()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", issue_id):
        raise HTTPException(status_code=422, detail="Linear issue ID 格式无效。")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="评论内容不能为空。")
    try:
        data = await _graphql(token, _COMMENT_CREATE_MUTATION, {"input": {
            "issueId": issue_id,
            "body": body,
        }})
    except LinearAPIError as exc:
        _raise_linear_error(exc)

    result = data.get("commentCreate")
    comment = result.get("comment") if isinstance(result, dict) else None
    if not isinstance(result, dict) or result.get("success") is not True or not isinstance(comment, dict):
        raise HTTPException(status_code=502, detail="Linear 未确认评论创建成功。")
    return {"id": str(comment.get("id") or ""), "body": str(comment.get("body") or body)}


__all__ = ["router"]
