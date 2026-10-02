"""Local fault injection provider with deterministic recovery and usage."""
import json
import math
import socket
import threading
from http.client import HTTPException
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FaultProxy:
    def __init__(self, faults=None, response="recovered", usage=None, upstream_url=None, timeout=15.0):
        self.faults = list(faults if faults is not None else ["429", "500", "disconnect"])
        if any(str(f) not in {"429", "500", "disconnect"} for f in self.faults):
            raise ValueError("unknown fault")
        self.upstream_url = self._validate_upstream(upstream_url)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("timeout must be finite and between 0 and 300 seconds")
        self.timeout = float(timeout)
        self.response = response
        self.usage = usage or {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
        self.requests = []
        self._lock = threading.Lock()
        self._server = None

    @staticmethod
    def _validate_upstream(value):
        if value is None:
            return None
        if not isinstance(value, str) or not value or any(ord(char) < 32 or char.isspace() for char in value):
            raise ValueError("upstream_url must be a valid HTTP(S) base URL")
        try:
            parsed = urllib.parse.urlsplit(value)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("upstream_url must be a valid HTTP(S) base URL") from exc
        if (parsed.scheme.lower() not in {"http", "https"} or not hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or "?" in value or "#" in value):
            raise ValueError("upstream_url must be HTTP(S), without credentials, query, or fragment")
        return value.rstrip("/")

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4 * 1024 * 1024:
                        self.send_error(413)
                        return
                    body = self.rfile.read(size)
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("body must be an object")
                except (ValueError, json.JSONDecodeError):
                    self.send_error(400)
                    return
                with owner._lock:
                    index = len(owner.requests)
                    fault = str(owner.faults[index]) if index < len(owner.faults) else None
                    # Metadata only: never persist headers, secrets or prompts.
                    metadata = {"index": index, "fault": fault, "stream": bool(payload.get("stream")),
                                "status": None, "completed": False}
                    owner.requests.append(metadata)
                if fault in {"429", "500"}:
                    data = json.dumps({"error": {"message": "scripted fault", "type": "rate_limit_error" if fault == "429" else "server_error"}}).encode()
                    self.send_response(int(fault))
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    self.wfile.write(data)
                    metadata["status"] = int(fault)
                    return
                if fault == "disconnect":
                    if payload.get("stream"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
                        self.wfile.flush()
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    metadata["status"] = 200 if payload.get("stream") else None
                    return
                if owner.upstream_url:
                    owner._forward(self, body, metadata)
                    return
                if payload.get("stream"):
                    events = [
                        {"id": "fake", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": owner.response}, "finish_reason": None}]},
                        {"id": "fake", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": owner.usage},
                    ]
                    data = ("".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n").encode()
                    content_type = "text/event-stream"
                else:
                    data = json.dumps({"id": "fake", "object": "chat.completion", "model": "local-fake", "choices": [{"index": 0, "message": {"role": "assistant", "content": owner.response}, "finish_reason": "stop"}], "usage": owner.usage}).encode()
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                metadata["status"] = 200
                metadata["usage"] = owner._usage_metadata(owner.usage)
                metadata["completed"] = True
                if payload.get("stream"):
                    metadata["stream_done"] = True

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = "http://127.0.0.1:%d/v1" % self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    @staticmethod
    def _usage_metadata(usage):
        if not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        cached = usage.get("prompt_tokens_details", {}).get("cached_tokens") if isinstance(usage.get("prompt_tokens_details"), dict) else usage.get("cached_tokens")
        result = {}
        for key, value in (("input_tokens", prompt), ("output_tokens", completion), ("cached_tokens", cached), ("cost_usd", usage.get("cost_usd"))):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                result[key] = value
        return result or None

    def _forward(self, handler, body, metadata):
        url = self.upstream_url + "/chat/completions"
        hop_by_hop = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
                      "trailers", "transfer-encoding", "upgrade", "host", "content-length", "expect"}
        connection_tokens = {token.strip().lower() for token in handler.headers.get("Connection", "").split(",") if token.strip()}
        excluded = hop_by_hop | connection_tokens
        headers = {name: value for name, value in handler.headers.items() if name.lower() not in excluded}
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        response = None
        headers_sent = False
        try:
            try:
                response = opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            status = response.getcode()
            metadata["status"] = status
            content_type = response.headers.get("Content-Type")
            handler.send_response(status)
            response_hop_by_hop = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
                                   "trailers", "transfer-encoding", "upgrade", "content-length", "set-cookie"}
            for name, value in response.headers.items():
                if name.lower() not in response_hop_by_hop:
                    handler.send_header(name, value)
            handler.end_headers()
            headers_sent = True
            is_stream = bool(metadata["stream"]) or bool(content_type and "text/event-stream" in content_type.lower())
            capture = bytearray()
            capture_complete = True
            bytes_forwarded = 0
            pending = bytearray()

            def process_sse_line(line):
                if not line.startswith(b"data:"):
                    return
                data = line[5:].strip()
                if data == b"[DONE]":
                    metadata["stream_done"] = True
                elif data:
                    self._record_sse_usage(metadata, data)

            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
                bytes_forwarded += len(chunk)
                remaining_capture = max(0, 8 * 1024 * 1024 - len(capture))
                capture.extend(chunk[:remaining_capture])
                if len(chunk) > remaining_capture:
                    capture_complete = False
                if is_stream:
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        process_sse_line(line.rstrip(b"\r"))
                        if len(pending) > 1024 * 1024:
                            pending.clear()
                            break
            if is_stream and pending:
                process_sse_line(bytes(pending).rstrip(b"\r"))
            if not is_stream and capture_complete:
                try:
                    parsed = json.loads(capture)
                    if isinstance(parsed, dict):
                        metadata["usage"] = self._usage_metadata(parsed.get("usage"))
                        metadata["completed"] = status == 200 and bytes_forwarded == len(capture)
                except (ValueError, UnicodeDecodeError):
                    pass
            elif is_stream:
                metadata["completed"] = status == 200 and metadata.get("stream_done") is True
        except (OSError, urllib.error.URLError, TimeoutError, HTTPException) as exc:
            metadata["upstream_error"] = type(exc).__name__
            if not headers_sent:
                metadata["status"] = 502
                try:
                    handler.send_error(502, "upstream request failed")
                except (OSError, BrokenPipeError):
                    pass
        finally:
            if response is not None:
                response.close()

    def _record_sse_usage(self, metadata, data):
        try:
            item = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        usage = item.get("usage") if isinstance(item, dict) else None
        normalized = self._usage_metadata(usage)
        if normalized:
            metadata["usage"] = normalized
