import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys


def serve(config_path):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != config["health_path"]:
                self.send_error(404)
                return
            body = b'{"status":"ok","service":"atlas-t1"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, fmt, *args):
            print("http:", fmt % args, flush=True)
    server = HTTPServer((config["host"], config["port"]), Handler)
    port_path = Path(config_path).with_suffix(".port")
    temp_path = port_path.with_suffix(port_path.suffix + ".tmp")
    try:
        temp_path.write_text(str(server.server_address[1]), encoding="ascii")
        temp_path.replace(port_path)
        print(f"LISTENING {server.server_address[1]}", flush=True)
        server.handle_request()
    finally:
        server.server_close()
        port_path.unlink(missing_ok=True)
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        serve(sys.argv[1] if len(sys.argv) > 1 else "service.json")
    except Exception as exc:
        print(f"startup failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
