#!/usr/bin/env bash
# T6-11 real-renderer acceptance: one isolated Electron window mounting the
# candidate tree's real ShortcutReferenceHost, real ShortcutsPanel and the real
# Atlas Dialog, backed by a temporary uvicorn that mounts the real u6 router.
set -u

ROOT="D:/Atlas/.worktrees/zcode-par10-shortcut-reference"
HARNESS="$ROOT/.tmp/par10-t6-11/electron"
RUN="$ROOT/.tmp/par10-t6-11/electron-run"
EVID="$ROOT/.tmp/par10-t6-11/electron-evidence"
ELECTRON="D:/Atlas/node_modules/electron/dist/electron.exe"
ESBUILD="D:/Atlas/node_modules/.bin/esbuild"

rm -rf "$RUN"
rm -f "$EVID"/par10-t6-11-electron-*
mkdir -p "$RUN/data-root/data" "$RUN/userdata" "$EVID"

cd "$HARNESS" || exit 3
"$ESBUILD" harness.tsx --bundle --format=iife --jsx=automatic \
  --define:process.env.NODE_ENV='"production"' --define:import.meta.env='{}' --outfile=bundle.js \
  > "$EVID/par10-t6-11-electron-esbuild.log" 2>&1
BUILD_EXIT=$?
echo "esbuild exit: $BUILD_EXIT"
if [ "$BUILD_EXIT" != "0" ]; then
  cat "$EVID/par10-t6-11-electron-esbuild.log"
  exit "$BUILD_EXIT"
fi

PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
echo "backend port: $PORT"

ATLAS_DATA_DIR="$RUN/data-root" PYTHONPATH="$ROOT/core" \
  python "$HARNESS/backend_app.py" --port "$PORT" > "$EVID/par10-t6-11-electron-backend.log" 2>&1 &
BACKEND_PID=$!

READY=0
for _ in $(seq 1 150); do
  if curl -fsS "http://127.0.0.1:$PORT/api/u6/keybindings" > "$EVID/par10-t6-11-electron-baseline-get.json" 2>/dev/null; then
    READY=1
    break
  fi
  sleep 0.2
done
echo "backend ready: $READY"
if [ "$READY" != "1" ]; then
  echo "backend did not start"
  kill "$BACKEND_PID" 2>/dev/null
  exit 4
fi

"$ELECTRON" --user-data-dir="$RUN/userdata" "$HARNESS/driver.cjs" \
  --url="http://127.0.0.1:$PORT/" --out="$EVID" --run="$RUN" \
  > "$EVID/par10-t6-11-electron-stdout.txt" 2>&1
ELECTRON_EXIT=$?
echo "electron exit: $ELECTRON_EXIT"

kill "$BACKEND_PID" 2>/dev/null
wait "$BACKEND_PID" 2>/dev/null
BACKEND_EXIT=$?
echo "backend exit: $BACKEND_EXIT"

if [ -f "$RUN/data-root/data/keybindings.json" ]; then
  cp "$RUN/data-root/data/keybindings.json" "$EVID/par10-t6-11-electron-keybindings-final.json"
fi

VALIDATE_EXIT=0
python - "$ELECTRON_EXIT" "$BACKEND_EXIT" "$EVID" <<'PY' || VALIDATE_EXIT=$?
import json, pathlib, sys

electron_exit, backend_exit, evidence = int(sys.argv[1]), int(sys.argv[2]), pathlib.Path(sys.argv[3])
summary_path = evidence / "par10-t6-11-electron-summary.json"
problems = []
if electron_exit != 0:
    problems.append(f"electron exit {electron_exit}")
if backend_exit not in (0, -15, 143):
    problems.append(f"backend exit {backend_exit}")
if not summary_path.exists():
    problems.append("missing summary")
    summary = {}
else:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    problems.extend(summary.get("problems") or [])
    if summary.get("result") != "PASS":
        problems.append(f"summary result {summary.get('result')}")
    if not summary.get("openedByRealInput"):
        problems.append("reference did not open from a real Electron input event")
final_path = evidence / "par10-t6-11-electron-keybindings-final.json"
final = json.loads(final_path.read_text(encoding="utf-8")) if final_path.exists() else {}
if (final.get("palette") or [None])[0] != "Ctrl+Alt+U":
    problems.append(f"final palette {final.get('palette')}")
if (final.get("newTask") or [None])[0] != "Ctrl+N":
    problems.append(f"final newTask {final.get('newTask')}")
shots = sorted(p.name for p in evidence.glob("par10-t6-11-electron-*.png"))
if len(shots) < 8:
    problems.append(f"too few screenshots: {len(shots)}")
result = {"result": "PASS" if not problems else "FAIL", "problems": problems, "screenshots": shots}
print(json.dumps(result, ensure_ascii=False))
if problems:
    print("\n".join(problems))
    sys.exit(1)
PY

echo "validate exit: $VALIDATE_EXIT"
if [ "$ELECTRON_EXIT" != "0" ] || [ "$VALIDATE_EXIT" != "0" ]; then
  exit 1
fi
exit 0