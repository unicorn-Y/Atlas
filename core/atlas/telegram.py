"""Telegram outbound polling channel. Secrets are stored only by the OS credential store."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

NOTIFY_EVENTS = {"completed", "failed", "approval"}
TOKEN_KEY = "atlas.telegram.bot_token"


class KeyringCredentialStore:
    def get(self, key: str) -> str | None:
        import keyring
        return keyring.get_password("Atlas", key)

    def set(self, key: str, value: str) -> None:
        import keyring
        keyring.set_password("Atlas", key, value)

    def delete(self, key: str) -> None:
        import keyring
        try:
            keyring.delete_password("Atlas", key)
        except keyring.errors.PasswordDeleteError:
            pass


class TelegramService:
    def __init__(
        self, settings_path: str | Path, *, credentials: Any | None = None,
        owns_lease: Callable[[], bool] | None = None,
        submit_task: Callable[..., Any] | None = None,
        command_handler: Callable[..., Any] | None = None,
        client_factory: Callable[..., Any] = httpx.AsyncClient,
    ) -> None:
        self.settings_path = Path(settings_path)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials = credentials or KeyringCredentialStore()
        self.owns_lease = owns_lease or (lambda: True)
        self.submit_task = submit_task
        self.command_handler = command_handler
        self.client_factory = client_factory
        self._poll_task: asyncio.Task[Any] | None = None
        self._approvals: dict[str, dict[str, Any]] = {}
        self._offset = 0
        self._active: dict[int, str] = {}

    def settings(self) -> dict[str, Any]:
        try:
            values = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            values = {}
        return {
            "enabled": bool(values.get("enabled", False)),
            "bot_token_set": bool(self.credentials.get(TOKEN_KEY)),
            "allowed_user_ids": [int(value) for value in values.get("allowed_user_ids", [])
                                 if isinstance(value, int) and not isinstance(value, bool)],
            "default_workspace": str(values.get("default_workspace", "")),
            "notify_on": [
                value for value in values.get("notify_on", ["completed", "failed", "approval"])
                if value in NOTIFY_EVENTS
            ],
        }

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        if "enabled" in values:
            if not isinstance(values["enabled"], bool):
                raise ValueError("开关值无效。")
            current["enabled"] = values["enabled"]
        if "allowed_user_ids" in values:
            ids = values["allowed_user_ids"]
            if not isinstance(ids, list) or any(
                type(value) is not int or value <= 0 for value in ids
            ):
                raise ValueError("授权用户编号必须是正整数列表。")
            current["allowed_user_ids"] = list(dict.fromkeys(ids))
        if "default_workspace" in values:
            workspace = values["default_workspace"]
            if not isinstance(workspace, str):
                raise ValueError("工作目录格式无效。")
            current["default_workspace"] = workspace
        if "notify_on" in values:
            notify = values["notify_on"]
            if not isinstance(notify, list) or any(item not in NOTIFY_EVENTS for item in notify):
                raise ValueError("通知选项无效。")
            current["notify_on"] = list(dict.fromkeys(notify))
        token = values.get("bot_token")
        if token is not None:
            if not isinstance(token, str) or not token.strip():
                raise ValueError("机器人密钥不能为空。")
            self.credentials.set(TOKEN_KEY, token.strip())
        self.settings_path.write_text(json.dumps({
            "enabled": current["enabled"],
            "allowed_user_ids": current["allowed_user_ids"],
            "default_workspace": current["default_workspace"],
            "notify_on": current["notify_on"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.settings()

    def start(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop(), name="atlas-telegram-poll")

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None

    async def test_token(self) -> dict[str, str]:
        token = self.credentials.get(TOKEN_KEY)
        if not token:
            raise ValueError("请先保存机器人密钥。")
        response = await self._request("getMe", token=token)
        if not response.get("ok"):
            raise ValueError("机器人密钥验证失败，请检查后重试。")
        return {"username": str(response.get("result", {}).get("username", ""))}

    async def _poll_loop(self) -> None:
        while True:
            config = self.settings()
            token = self.credentials.get(TOKEN_KEY)
            if not config["enabled"] or not token or not self.owns_lease():
                await asyncio.sleep(1.0)
                continue
            try:
                result = await self._request("getUpdates", token=token, payload={
                    "offset": self._offset, "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                }, timeout=35.0)
                if not self.owns_lease():
                    continue
                if result.get("ok"):
                    for update in result.get("result", []):
                        self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
                        await self.process_update(update)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(2.0)

    async def _request(
        self, method: str, *, token: str | None = None,
        payload: dict[str, Any] | None = None, timeout: float = 20.0,
    ) -> dict[str, Any]:
        token = token or self.credentials.get(TOKEN_KEY)
        if not token:
            raise ValueError("机器人密钥未配置。")
        try:
            async with self.client_factory(timeout=timeout) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/{method}", json=payload or {},
                )
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {"ok": False}
        except asyncio.CancelledError:
            raise
        except Exception:
            # Client exceptions may contain the secret-bearing Bot API URL.
            raise RuntimeError("Telegram 请求失败。") from None

    async def send_message(
        self, user_id: int, text: str, reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": int(user_id), "text": str(text)[:4096]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        await self._request("sendMessage", payload=payload)

    async def process_update(self, update: dict[str, Any]) -> None:
        config = self.settings()
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            user_id = int((callback.get("from") or {}).get("id", 0))
            if user_id not in config["allowed_user_ids"]:
                return
            await self._answer_approval(str(callback.get("data", "")), user_id, callback)
            return
        message = update.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("text"), str):
            return
        user_id = int((message.get("from") or {}).get("id", 0))
        if user_id not in config["allowed_user_ids"]:
            return
        text = message["text"].strip()
        if text.startswith("/"):
            if self.command_handler:
                response = self.command_handler(text, user_id)
                response = await response if hasattr(response, "__await__") else response
                if response:
                    await self.send_message(user_id, str(response))
            return
        if self.submit_task is not None:
            asyncio.create_task(self._submit_and_notify(text, user_id, config))

    async def _submit_and_notify(self, text: str, user_id: int, config: dict[str, Any]) -> None:
        try:
            response = self.submit_task(text, user_id, self)
            result = await response if hasattr(response, "__await__") else response
            if "completed" in config["notify_on"]:
                await self.send_message(user_id, str(result.get("summary", "任务已完成。"))[:1500])
        except asyncio.CancelledError:
            raise
        except Exception:
            if "failed" in config["notify_on"]:
                await self.send_message(user_id, "任务执行失败，请在 Atlas 桌面端查看详情。")

    async def request_approval(
        self, user_id: int, run_id: str, approval_id: str, description: str,
    ) -> asyncio.Future[str]:
        config = self.settings()
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        if "approval" not in config["notify_on"]:
            future.set_result("deny")
            return future
        allow_id, deny_id = secrets.token_urlsafe(7)[:10], secrets.token_urlsafe(7)[:10]
        for callback_id, choice in ((allow_id, "allow"), (deny_id, "deny")):
            self._approvals[callback_id] = {
                "user_id": user_id, "run_id": run_id, "approval_id": approval_id,
                "expires": time.time() + 600, "future": future, "choice": choice,
            }
        keyboard = {"inline_keyboard": [[
            {"text": "允许", "callback_data": allow_id},
            {"text": "拒绝", "callback_data": deny_id},
        ]]}
        await self.send_message(user_id, "需要确认：" + description[:600], keyboard)
        return future

    async def _answer_approval(self, data: str, user_id: int, callback: dict[str, Any]) -> None:
        record = self._approvals.pop(data, None)
        if (record is None or record["user_id"] != user_id
                or record["expires"] < time.time()):
            return
        future = record["future"]
        if not future.done():
            future.set_result(record["choice"])
        with __import__("contextlib").suppress(Exception):
            await self._request("answerCallbackQuery", payload={
                "callback_query_id": callback.get("id", ""), "text": "已记录你的选择。",
            })
