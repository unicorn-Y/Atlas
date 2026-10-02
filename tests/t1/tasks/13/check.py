import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

root = Path(sys.argv[1])
task = Path(__file__).parent
config = json.loads((root / "service.json").read_text(encoding="utf-8"))
assert config["host"] == "127.0.0.1" and config["port"] == 0
assert config["health_path"] == "/health"
proc = subprocess.Popen([sys.executable, str(root / "service.py"), str(root / "service.json")],
                        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        encoding="utf-8", errors="replace")
port_file = root / "service.port"
port_tmp = root / "service.port.tmp"


def stop_process_tree():
    # The interpreter executable can be a launcher that owns a separate Python
    # child. Terminate the whole tree before touching files that child may own.
    if proc.poll() is None and os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    elif proc.poll() is None:
        proc.terminate()
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=5)


def remove_after_exit(path):
    deadline = time.monotonic() + 3
    while True:
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


try:
    deadline = time.monotonic() + 5
    port = None
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            port = int(port_file.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            port = None
        if port:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and body == {"status": "ok", "service": "atlas-t1"}:
                    break
            except (OSError, ValueError):
                pass
        time.sleep(0.03)
    else:
        if proc.poll() is None:
            raise AssertionError("service readiness timed out")
        _, stderr = proc.communicate(timeout=3)
        raise AssertionError(f"service did not start; stderr={stderr[-1000:]}")
finally:
    stop_process_tree()
    remove_after_exit(port_file)
    remove_after_exit(port_tmp)
print("loopback service health: PASS")
