import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fault_proxy import FaultProxy
from fault_proxy.client import recover


class LoopbackUpstream:
    def __init__(self, body, content_type, delay=0):
        self.body = body
        self.content_type = content_type
        self.delay = delay
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                owner.requests.append({"path": self.path,
                                       "body": self.rfile.read(length),
                                       "authorization": self.headers.get("Authorization"),
                                       "api_key": self.headers.get("api-key")})
                if owner.delay:
                    time.sleep(owner.delay)
                self.send_response(200)
                self.send_header("Content-Type", owner.content_type)
                self.send_header("Content-Length", str(len(owner.body)))
                self.end_headers()
                try:
                    self.wfile.write(owner.body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class FaultTests(unittest.TestCase):
    def request(self, proxy, stream=False):
        req = urllib.request.Request(proxy.url + "/chat/completions", data=json.dumps({"model": "fake", "messages": [], "stream": stream}).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer do-not-record"})
        return urllib.request.urlopen(req, timeout=3).read()

    def test_script_and_usage(self):
        with FaultProxy() as proxy:
            for status in (429, 500):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request(proxy)
                self.assertEqual(caught.exception.code, status)
            with self.assertRaises(Exception):
                self.request(proxy)
            result = json.loads(self.request(proxy))
            self.assertEqual(result["usage"]["total_tokens"], 15)
            self.assertEqual(result["choices"][0]["message"]["content"], "recovered")
            self.assertNotIn("do-not-record", json.dumps(proxy.requests))
            self.assertTrue(proxy.requests[-1]["completed"])
            self.assertTrue(all(not request["completed"] for request in proxy.requests[:-1]))

    def test_partial_stream_then_complete(self):
        with FaultProxy(["disconnect"]) as proxy:
            partial = self.request(proxy, True)
            self.assertIn(b"partial", partial)
            self.assertNotIn(b"[DONE]", partial)
            self.assertFalse(proxy.requests[-1]["completed"])
            self.assertFalse(proxy.requests[-1].get("stream_done", False))
            complete = self.request(proxy, True)
            self.assertIn(b"[DONE]", complete)
            self.assertIn(b"usage", complete)
            self.assertTrue(proxy.requests[-1]["completed"])
            self.assertTrue(proxy.requests[-1]["stream_done"])

    def test_bad_fault_rejected(self):
        with self.assertRaises(ValueError):
            FaultProxy(["unrecognized"])

    def test_client_recovery_drops_partial_content(self):
        with FaultProxy() as proxy:
            result = recover(proxy.url)
            self.assertEqual([step.get("error") for step in result["history"]], ["429", "500", "disconnect", None])
            self.assertEqual(result["content"], "recovered")
            self.assertEqual(result["usage"]["total_tokens"], 15)

    def test_client_never_contacts_upstream(self):
        with self.assertRaises(ValueError):
            recover("https://api.openai.com/v1")

    def test_opt_in_forwarding_preserves_json_and_auth_after_faults(self):
        usage = {"prompt_tokens": 21, "completion_tokens": 5, "total_tokens": 26,
                 "prompt_tokens_details": {"cached_tokens": 3}, "cost_usd": 0.004}
        body = json.dumps({"id": "upstream-json", "choices": [{"message": {"content": "native answer"}}],
                           "usage": usage}, separators=(",", ":")).encode()
        upstream = LoopbackUpstream(body, "application/json")
        try:
            with FaultProxy(upstream_url=upstream.url) as proxy:
                payload = json.dumps({"model": "private-model", "messages": [{"role": "user", "content": "private prompt marker"}],
                                      "stream": False}, separators=(",", ":")).encode()
                headers = {"Content-Type": "application/json", "Authorization": "Bearer auth-marker",
                           "api-key": "api-key-marker"}
                for status in (429, 500):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        self._post(proxy.url + "/chat/completions", payload, headers)
                    self.assertEqual(caught.exception.code, status)
                with self.assertRaises(Exception):
                    self._post(proxy.url + "/chat/completions", payload, headers)
                forwarded = self._post(proxy.url + "/chat/completions", payload, headers)
                self.assertEqual(forwarded, body)
                self.assertEqual(upstream.requests, [{"path": "/v1/chat/completions", "body": payload,
                                                      "authorization": "Bearer auth-marker", "api_key": "api-key-marker"}])
                self.assertEqual([request["status"] for request in proxy.requests], [429, 500, None, 200])
                self.assertEqual(proxy.requests[-1]["usage"], {"input_tokens": 21, "output_tokens": 5,
                                                                  "cached_tokens": 3, "cost_usd": 0.004})
                self.assertTrue(proxy.requests[-1]["completed"])
                recorded = json.dumps(proxy.requests)
                for secret in ("auth-marker", "api-key-marker", "private prompt marker", "private-model"):
                    self.assertNotIn(secret, recorded)
        finally:
            upstream.close()

    def test_opt_in_forwarding_preserves_sse_bytes_and_native_usage(self):
        events = [
            {"id": "native", "choices": [{"delta": {"content": "partial answer"}, "finish_reason": None}]},
            {"id": "native", "choices": [{"delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 17, "completion_tokens": 4, "total_tokens": 21}},
        ]
        body = ("".join("data: " + json.dumps(event, separators=(",", ":")) + "\n\n" for event in events)
                + "data: [DONE]\n\n").encode()
        upstream = LoopbackUpstream(body, "text/event-stream")
        try:
            with FaultProxy(upstream_url=upstream.url) as proxy:
                payload = json.dumps({"messages": [{"role": "user", "content": "sse marker"}], "stream": True}).encode()
                headers = {"Content-Type": "application/json", "Authorization": "Bearer sse-auth-marker"}
                for _ in range(2):
                    with self.assertRaises(urllib.error.HTTPError):
                        self._post(proxy.url + "/chat/completions", payload, headers)
                partial = self._post(proxy.url + "/chat/completions", payload, headers)
                self.assertIn(b"partial", partial)
                self.assertNotIn(b"[DONE]", partial)
                forwarded = self._post(proxy.url + "/chat/completions", payload, headers)
                self.assertEqual(forwarded, body)
                self.assertEqual(upstream.requests[0]["body"], payload)
                self.assertEqual(upstream.requests[0]["authorization"], "Bearer sse-auth-marker")
                self.assertEqual(proxy.requests[-1]["usage"], {"input_tokens": 17, "output_tokens": 4})
                self.assertTrue(proxy.requests[-1]["completed"])
                self.assertTrue(proxy.requests[-1]["stream_done"])
                recorded = json.dumps(proxy.requests)
                self.assertNotIn("sse-auth-marker", recorded)
                self.assertNotIn("sse marker", recorded)
        finally:
            upstream.close()

    def test_partial_upstream_200_stream_without_done_is_not_complete(self):
        body = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        upstream = LoopbackUpstream(body, "text/event-stream")
        try:
            with FaultProxy(faults=[], upstream_url=upstream.url) as proxy:
                forwarded = self._post(proxy.url + "/chat/completions", b'{"stream":true}',
                                       {"Content-Type": "application/json"})
                self.assertEqual(forwarded, body)
                self.assertEqual(proxy.requests[0]["status"], 200)
                self.assertFalse(proxy.requests[0]["completed"])
                self.assertFalse(proxy.requests[0].get("stream_done", False))
        finally:
            upstream.close()

    def test_upstream_url_rejects_credentials_and_malformed_values(self):
        for url in ("ftp://127.0.0.1/v1", "http://user:pass@127.0.0.1/v1",
                    "http://127.0.0.1/v1?token=secret", "http://[invalid/v1", "not a url"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                FaultProxy(upstream_url=url)
        with self.assertRaises(ValueError):
            FaultProxy(timeout=float("inf"))

    def test_upstream_request_timeout_is_finite(self):
        upstream = LoopbackUpstream(b"{}", "application/json", delay=0.2)
        try:
            with FaultProxy(faults=[], upstream_url=upstream.url, timeout=0.05) as proxy:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self._post(proxy.url + "/chat/completions", b'{"stream":false}',
                               {"Content-Type": "application/json"})
                self.assertEqual(caught.exception.code, 502)
                self.assertEqual(proxy.requests[0]["status"], 502)
                self.assertEqual(proxy.requests[0]["upstream_error"], "TimeoutError")
        finally:
            upstream.close()

    @staticmethod
    def _post(url, payload, headers):
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        return urllib.request.urlopen(request, timeout=3).read()


if __name__ == "__main__":
    unittest.main()
