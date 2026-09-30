"""User-authored script tools stored under Atlas's data directory."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

_TOOL_ID = re.compile(r"[a-z0-9-]{1,64}\Z")
MAX_OUTPUT = 64 * 1024


class CustomToolStore:
    def __init__(self, tools_dir: str | Path) -> None:
        self.tools_dir = Path(tools_dir).resolve()

    def list_tools(self) -> list[dict[str, Any]]:
        result = []
        if not self.tools_dir.is_dir():
            return result
        for config_path in sorted(self.tools_dir.glob("*/tool.json")):
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if self._valid_id(data.get("id")) and data["id"] == config_path.parent.name:
                    result.append(data)
            except (OSError, ValueError, KeyError):
                continue
        return result

    @staticmethod
    def _valid_id(tool_id: Any) -> bool:
        return isinstance(tool_id, str) and _TOOL_ID.fullmatch(tool_id) is not None

    def _directory(self, tool_id: str) -> Path:
        if not self._valid_id(tool_id):
            raise ValueError("工具编号只能使用小写英文字母、数字和连字符。")
        return self.tools_dir / tool_id

    @staticmethod
    def _normalize(data: dict[str, Any], tool_id: str) -> dict[str, Any]:
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("请填写工具名称。")
        if not isinstance(data.get("description"), str):
            raise ValueError("请填写工具说明。")
        command = data.get("command")
        if not isinstance(command, list) or not command or any(
            not isinstance(item, str) or not item or "\x00" in item for item in command
        ):
            raise ValueError("命令必须是非空的参数数组。")
        schema = data.get("input_schema", {"type": "object", "properties": {}})
        if not isinstance(schema, dict) or schema.get("type", "object") != "object":
            raise ValueError("参数格式必须是对象。")
        timeout = data.get("timeout_s", 30)
        if not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 300:
            raise ValueError("超时时间必须在 0.1 到 300 秒之间。")
        return {"id": tool_id, "name": data["name"].strip(),
                "description": data["description"].strip(), "command": command,
                "input_schema": schema, "timeout_s": float(timeout),
                "enabled": bool(data.get("enabled", True))}

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        tool_id = data.get("id")
        directory = self._directory(tool_id)
        if directory.exists():
            raise ValueError("这个工具编号已经存在。")
        config = self._normalize(data, tool_id)
        directory.mkdir(parents=True)
        try:
            script_name, script = data.get("script_name"), data.get("script")
            if script is not None or script_name is not None:
                if (not isinstance(script_name, str) or not script_name
                        or Path(script_name).name != script_name or "/" in script_name
                        or "\\" in script_name or script_name in {".", ".."}):
                    raise ValueError("脚本文件名不能包含目录。")
                if not isinstance(script, str):
                    raise ValueError("脚本内容必须是文字。")
                (directory / script_name).write_text(script, encoding="utf-8")
            self._write_config(directory, config)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return config

    def update(self, tool_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        directory = self._directory(tool_id)
        config_path = directory / "tool.json"
        if not config_path.is_file():
            return None
        current = json.loads(config_path.read_text(encoding="utf-8"))
        values = {**current, **{key: value for key, value in data.items()
                                if key not in {"script", "script_name"}}, "id": tool_id}
        config = self._normalize(values, tool_id)
        if "script" in data or "script_name" in data:
            name, script = data.get("script_name"), data.get("script")
            if (not isinstance(name, str) or not name or Path(name).name != name
                    or "/" in name or "\\" in name or name in {".", ".."}
                    or not isinstance(script, str)):
                raise ValueError("脚本文件名或内容无效。")
            (directory / name).write_text(script, encoding="utf-8")
        self._write_config(directory, config)
        return config

    def delete(self, tool_id: str) -> bool:
        directory = self._directory(tool_id)
        if not directory.is_dir():
            return False
        shutil.rmtree(directory)
        return True

    @staticmethod
    def _write_config(directory: Path, data: dict[str, Any]) -> None:
        temporary = directory / "tool.json.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "tool.json")

    @staticmethod
    def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是 JSON 对象。")
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in arguments]
        if missing:
            raise ValueError("缺少必要参数：" + ", ".join(missing))
        if schema.get("additionalProperties") is False:
            unknown = set(arguments) - set(properties)
            if unknown:
                raise ValueError("包含未定义的参数：" + ", ".join(sorted(unknown)))
        for key, value in arguments.items():
            spec = properties.get(key, {})
            expected = spec.get("type")
            matches = {
                "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool), "array": isinstance(value, list),
                "object": isinstance(value, dict),
            }
            if expected in matches and not matches[expected]:
                raise ValueError(f"参数 {key} 的格式不正确。")

    async def execute(self, tool_id: str, arguments: dict[str, Any], *, allow_disabled: bool = False) -> dict[str, Any]:
        directory = self._directory(tool_id)
        config_path = directory / "tool.json"
        if not config_path.is_file():
            raise KeyError(tool_id)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not config.get("enabled") and not allow_disabled:
            raise ValueError("这个工具已停用。")
        self._validate_arguments(config["input_schema"], arguments)
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            *config["command"], cwd=directory, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt", creationflags=creation_flags,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(arguments, ensure_ascii=False).encode("utf-8")),
                timeout=float(config.get("timeout_s", 30)),
            )
        except TimeoutError:
            await self._kill_tree(process)
            return {"error": "自定义工具运行超时。", "is_error": True}
        output = stdout.decode("utf-8", errors="replace")
        truncated = len(output.encode("utf-8")) > MAX_OUTPUT
        if truncated:
            output = output.encode("utf-8")[:MAX_OUTPUT].decode("utf-8", errors="ignore")
        try:
            value: Any = json.loads(output)
        except ValueError:
            value = output
        return {"result": value, "stderr": stderr.decode("utf-8", errors="replace")[:4096],
                "exit_code": process.returncode, "truncated": truncated,
                "is_error": process.returncode != 0}

    @staticmethod
    async def _kill_tree(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            await asyncio.to_thread(subprocess.run,
                                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    capture_output=True, check=False)
        else:
            with __import__("contextlib").suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        with __import__("contextlib").suppress(ProcessLookupError):
            process.kill()
        await process.wait()

    def model_tools(self) -> list[dict[str, Any]]:
        tools = []
        for config in self.list_tools():
            if not config.get("enabled"):
                continue
            tools.append({"type": "function", "function": {
                "name": f"custom_{config['id']}",
                "description": f"{config['description']}（{config['name']}）",
                "parameters": config["input_schema"],
            }})
        return tools
