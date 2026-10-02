import argparse
import json
import threading

from .server import FaultProxy


def main():
    parser = argparse.ArgumentParser(description="Local OpenAI-compatible provider with scripted faults; upstream forwarding is opt-in")
    parser.add_argument("--faults", default="429,500,disconnect")
    parser.add_argument("--upstream-url", help="explicit HTTP(S) upstream base URL; requests after scripted faults are forwarded")
    parser.add_argument("--timeout", type=float, default=15.0, help="finite upstream request timeout in seconds")
    args = parser.parse_args()
    with FaultProxy([x for x in args.faults.split(",") if x], upstream_url=args.upstream_url,
                    timeout=args.timeout) as proxy:
        print(json.dumps({"base_url": proxy.url, "model": "local-fake",
                          "forwarding": bool(proxy.upstream_url)}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
