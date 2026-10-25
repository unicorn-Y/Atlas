"""Python wrapper around Atlas' machine-readable CLI."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterator


@dataclass
class RunResult:
    session_id: str
    text: str
    events: list[dict[str, Any]]
    structured: Any = None


class Atlas:
    def __init__(self, executable: str = "atlas", *, env: dict[str, str] | None = None):
        self.executable = executable
        self.env = {**os.environ, **(env or {})}

    def stream(self, prompt: str, *, cwd: str | os.PathLike[str] | None = None,
               output_schema: dict[str, Any] | None = None,
               session_id: str | None = None) -> Iterator[dict[str, Any]]:
        command = [self.executable, "exec", "--json"]
        if cwd is not None:
            command.extend(["--cwd", str(Path(cwd).resolve())])
        if session_id:
            command.extend(["--resume", session_id])
        schema_path = None
        if output_schema is not None:
            import tempfile
            handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
            try:
                json.dump(output_schema, handle)
                schema_path = Path(handle.name)
            finally:
                handle.close()
            command.extend(["--output-schema", str(schema_path)])
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=self.env)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(prompt); process.stdin.close()
        try:
            for line in process.stdout:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
        finally:
            code = process.wait()
            if schema_path:
                schema_path.unlink(missing_ok=True)
            if code:
                assert process.stderr is not None
                raise RuntimeError(process.stderr.read() or f"atlas exec exited with code {code}")

    def run(self, prompt: str, *, cwd: str | os.PathLike[str] | None = None,
            output_schema: dict[str, Any] | None = None) -> RunResult:
        events = list(self.stream(prompt, cwd=cwd, output_schema=output_schema))
        session_id = next((str(item["session_id"]) for item in events if item.get("type") == "start"), "")
        # `final` carries the validated answer; text_delta also contains narration before tool calls.
        final = next((item for item in reversed(events) if item.get("type") == "final"), None)
        if final is not None:
            text = str(final.get("text", ""))
            structured = final.get("structured") if output_schema is not None else None
        else:
            text = "".join(str(item.get("text", "")) for item in events if item.get("type") == "text_delta")
            structured = json.loads(text) if output_schema is not None else None
        return RunResult(session_id=session_id, text=text, events=events, structured=structured)

    def resume(self, session_id: str, prompt: str = "Continue.", *, cwd: str | os.PathLike[str] | None = None) -> RunResult:
        events = list(self.stream(prompt, cwd=cwd, session_id=session_id))
        text = "".join(str(item.get("text", "")) for item in events if item.get("type") == "text_delta")
        return RunResult(session_id=session_id, text=text, events=events)
