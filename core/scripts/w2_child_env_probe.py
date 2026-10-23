"""Check inherited model keys are removed while explicit values survive."""
import os

from atlas.engine_core.tools.child_process_env import child_process_env


def main() -> None:
    old_api, old_other = os.environ.get("W2_FIXTURE_API_KEY"), os.environ.get("W2_FIXTURE_COLOR")
    try:
        os.environ["W2_FIXTURE_API_KEY"] = "secret-sentinel"
        os.environ["W2_FIXTURE_COLOR"] = "blue"
        inherited = child_process_env()
        assert "W2_FIXTURE_API_KEY" not in inherited
        assert inherited["W2_FIXTURE_COLOR"] == "blue"
        explicit = child_process_env({"W2_FIXTURE_API_KEY": "explicit-sentinel"})
        assert explicit["W2_FIXTURE_API_KEY"] == "explicit-sentinel"
    finally:
        if old_api is None:
            os.environ.pop("W2_FIXTURE_API_KEY", None)
        else:
            os.environ["W2_FIXTURE_API_KEY"] = old_api
        if old_other is None:
            os.environ.pop("W2_FIXTURE_COLOR", None)
        else:
            os.environ["W2_FIXTURE_COLOR"] = old_other
    print("W2-6 inherited credential scrub and explicit environment: PASS")


if __name__ == "__main__":
    main()
