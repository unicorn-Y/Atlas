"""Deterministic fake client used to verify fault recovery without API keys."""
import json
import urllib.error
import urllib.parse
import urllib.request


def recover(url, attempts=4, stream=True):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ValueError("fake client accepts only the local loopback fault provider")
    history = []
    for attempt in range(attempts):
        request = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=json.dumps({"model": "local-fake", "messages": [{"role": "user", "content": "recover"}], "stream": stream}).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                data = response.read().decode("utf-8")
            if stream:
                if "data: [DONE]" not in data:
                    history.append({"attempt": attempt + 1, "error": "disconnect"})
                    continue
                events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
                text = "".join(event.get("choices", [{}])[0].get("delta", {}).get("content", "") for event in events)
                usage = next((event["usage"] for event in events if "usage" in event), None)
            else:
                body = json.loads(data)
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage")
            history.append({"attempt": attempt + 1, "status": "success"})
            return {"history": history, "content": text, "usage": usage}
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500}:
                raise
            history.append({"attempt": attempt + 1, "error": str(exc.code)})
        except (urllib.error.URLError, OSError) as exc:
            history.append({"attempt": attempt + 1, "error": "disconnect"})
    raise RuntimeError("retry attempts exhausted: " + json.dumps(history))
