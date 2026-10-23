"""Small proof for bounded retries, status classification, and model breaker."""

from atlas.agent.fallback_cooldown import clear, is_cooling, record_failure, record_success
from atlas.kernel.model_call import _task_retry_budget, classify_error


def main() -> None:
    assert classify_error(RuntimeError("HTTP 429 too many requests")) == ("rate_limit", True, 429)
    assert classify_error(RuntimeError("HTTP 529 server overloaded")) == ("overloaded", True, 529)
    clear()
    assert not record_failure("primary")
    assert not record_failure("primary")
    assert record_failure("primary")
    assert is_cooling("primary")
    record_success("primary")
    assert not is_cooling("primary")
    assert _task_retry_budget() == (20, 300.0)
    print("status classes: 429 rate_limit; 529 overloaded")
    print("model breaker: opens on third consecutive overload; success resets it")
    print("task retry budget: 20 retries / 300 seconds by default")
    print("W1-1 RETRY PROBE PASS")


if __name__ == "__main__":
    main()
