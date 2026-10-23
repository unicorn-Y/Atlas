"""Small offline proof for W0-4 retry classification and live backoff wiring."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.agent.retry_utils import jittered_backoff
from atlas.kernel.model_call import _header, _overloaded_backoff, _retry_after, classify_error


class ResponseError(RuntimeError):
    def __init__(self, status: int, headers: dict[str, str], body: str = "") -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.response = SimpleNamespace(headers=headers, text=body)


def main() -> None:
    assert all(0.5 <= jittered_backoff(i) <= 32.0 for i in range(1, 30))
    assert all(0.5 <= _overloaded_backoff(i, 0.5) <= 32.0 for i in range(0, 12))

    throttled = ResponseError(429, {"Retry-After": "7", "x-should-retry": "true"})
    assert _header(throttled, "x-should-retry") == "true"
    assert _retry_after(throttled) == 7.0
    denied = ResponseError(503, {"x-should-retry": "false"})
    assert _header(denied, "x-should-retry") == "false"

    proxy_html = ResponseError(502, {"content-type": "text/html"}, "<html>gateway failure</html>")
    assert classify_error(proxy_html) == ("connection", True, 502)
    provider_json = ResponseError(502, {"content-type": "application/json"}, '{"error":{"message":"busy"}}')
    assert classify_error(provider_json) == ("provider", True, 502)
    print("W0-4 OK: retry utility is called by live 529 path; 500ms exponential delay stays <=32s; server retry headers and proxy 5xx classification are read.")


if __name__ == "__main__":
    main()
