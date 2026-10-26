"""U44 acceptance scenarios for upstream retry policy and all work items."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import Any

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


class _RelayRejection(RuntimeError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__("403 Forbidden: message: request illegal; type: bad_response_status_code")
        self.response = SimpleNamespace(
            status_code=403, headers={},
            text='{"error":{"message":"request illegal","type":"bad_response_status_code"}}',
        )


class _Unauthorized(RuntimeError):
    status_code = 401

    def __init__(self) -> None:
        super().__init__("401 Unauthorized: invalid api key")
        self.response = SimpleNamespace(status_code=401, headers={}, text='{"error":"invalid api key"}')


def _text_chunks() -> list[dict[str, Any]]:
    return [
        {"choices": [{"delta": {"content": "fixture-ok"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


class _Router:
    def __init__(self, scripts: dict[str, list[str]]) -> None:
        self.scripts = scripts
        self.calls: dict[str, int] = {}

    async def resolve(self, model: str, _purpose: str) -> Any:
        return SimpleNamespace(
            model=model, model_id=model, wire_model=model, provider="fixture-relay",
            base_url="http://127.0.0.1/fixture", api_mode="openai_compatible",
            credential_pool=None, key="fixture-only",
        )

    def stream(self, route: Any, _messages: Any, **_kwargs: Any) -> Any:
        model = route.model_id
        index = self.calls.get(model, 0)
        self.calls[model] = index + 1
        result = self.scripts[model][min(index, len(self.scripts[model]) - 1)]
        if result == "403":
            raise _RelayRejection()
        if result == "401":
            raise _Unauthorized()
        return _text_chunks()


async def check_upstream_retry_policy() -> None:
    from atlas.kernel.model_call import ModelCallError, classify_error, complete_stream

    category, retryable, status = classify_error(_RelayRejection())
    assert (category, retryable, status) == ("upstream_rejection", True, 403)
    assert classify_error(_Unauthorized()) == ("authentication", False, 401)
    ordinary_403 = RuntimeError("403 Forbidden: invalid permissions")
    ordinary_403.status_code = 403
    assert classify_error(ordinary_403) == ("authentication", False, 403)

    previous_attempts = os.environ.get("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS")
    previous_wait = os.environ.get("ATLAS_MODEL_RETRY_BUDGET_SECONDS")
    os.environ["ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS"] = "4"
    os.environ["ATLAS_MODEL_RETRY_BUDGET_SECONDS"] = "2"
    try:
        router = _Router({"primary": ["403", "403"], "backup": ["ok"]})
        attempts: list[dict[str, Any]] = []
        result = await complete_stream(
            SimpleNamespace(_model_router=router, source="foreground"), "primary",
            [{"role": "user", "content": "probe"}], [], max_retries=8,
            fallback_models=["backup"], on_attempt=attempts.append,
        )
        assert result.model == "backup" and result.text == "fixture-ok"
        assert router.calls == {"primary": 2, "backup": 1}, router.calls
        retried = [item for item in attempts
                   if item.get("category") == "upstream_rejection" and not item.get("fallback")]
        assert len(retried) == 2 and retried[0].get("retry") is True
        assert retried[0].get("retry_kind") == "upstream_rejection"
        assert retried[1].get("retry") is False

        auth_router = _Router({"primary": ["401"], "backup": ["ok"]})
        try:
            await complete_stream(
                SimpleNamespace(_model_router=auth_router, source="foreground"), "primary",
                [{"role": "user", "content": "probe"}], [], max_retries=8,
                fallback_models=["backup"],
            )
        except ModelCallError:
            pass
        assert auth_router.calls.get("primary") == 1, auth_router.calls
    finally:
        for key, value in (("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", previous_attempts),
                           ("ATLAS_MODEL_RETRY_BUDGET_SECONDS", previous_wait)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("U44 item 0 PASS: relay 403 retries once on the same model then uses fallback; 401 is not retried")


async def check_real_provider() -> None:
    from atlas.models import ModelManager
    from real_model_check import AttemptResult, retry_real_model_check_async

    async def attempt(prompt: str, attempt_number: int) -> AttemptResult:
        del attempt_number
        response = await ModelManager().model_router.complete_for(
            "deepseek-v4.1-flash", "advisor", [{"role": "user", "content": prompt}],
            max_tokens=48, temperature=0,
        )
        answer = str(response.text or "")
        return AttemptResult("U44_RETRY_HELPER_OK" in answer, answer=answer,
                             detail="required real-model marker missing")

    await retry_real_model_check_async(
        "U44 configured deepseek model route",
        "Reply with exactly U44_RETRY_HELPER_OK and no other text.", attempt,
    )


def main() -> None:
    sys.path.insert(0, str(CORE))
    asyncio.run(check_upstream_retry_policy())
    asyncio.run(check_real_provider())
    check_terminal_setup()
    print("U44 CHECK PASS")


def check_terminal_setup() -> None:
    from atlas.terminal_setup import detect_shell, integration_installed
    from atlas.cli import main as atlas_cli
    from click.testing import CliRunner

    assert detect_shell({"ATLAS_TERMINAL_SHELL": "bash"}) == "bash"
    with tempfile.TemporaryDirectory(prefix="atlas-u44-terminal-") as temp:
        profile = Path(temp) / ".bashrc"
        profile.write_text("# user profile\n", encoding="utf-8")
        runner = CliRunner()
        environment = {**os.environ, "ATLAS_TERMINAL_SHELL": "bash"}
        installed = runner.invoke(atlas_cli, ["terminal-setup", "--profile", str(profile)], env=environment)
        assert installed.exit_code == 0 and "已配置 bash" in installed.output, installed.output
        original_plus_block = profile.read_text(encoding="utf-8")
        assert "# user profile" in original_plus_block
        assert "ATLAS_SHELL_INTEGRATION=1" in original_plus_block
        assert "13;2u" in original_plus_block and integration_installed(profile)
        again = runner.invoke(atlas_cli, ["terminal-setup", "--profile", str(profile)], env=environment)
        assert again.exit_code == 0 and "已是最新" in again.output
        status = runner.invoke(atlas_cli, ["terminal-setup", "--status", "--profile", str(profile)], env=environment)
        assert status.exit_code == 0 and "installed=yes" in status.output
        removed = runner.invoke(atlas_cli, ["terminal-setup", "--remove", "--profile", str(profile)], env=environment)
        assert removed.exit_code == 0 and "已移除" in removed.output
        assert profile.read_text(encoding="utf-8").strip() == "# user profile"
        assert not integration_installed(profile)
        absent = runner.invoke(atlas_cli, ["terminal-setup", "--remove", "--profile", str(profile)], env=environment)
        assert absent.exit_code == 0 and "未找到" in absent.output
        bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if bash:
            checked = subprocess.run([str(bash), "-n"], input=original_plus_block, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=10)
            if bash.is_file():
                assert checked.returncode == 0, checked.stderr
    print("U44 item 4 PASS: shell detection, idempotent profile install, Shift+Enter binding, and exact managed-block removal")


if __name__ == "__main__":
    main()
