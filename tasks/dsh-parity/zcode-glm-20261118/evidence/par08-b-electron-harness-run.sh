#!/usr/bin/env bash
# Real dual-window acceptance: two isolated Electron processes drive the actual
# ShortcutsPanel against a temporary uvicorn hosting the worktree u6 router.
set -u

ROOT="D:/Atlas/.worktrees/zcode-exec06-keybindings-cas"
HARNESS="$ROOT/.tmp/par08b-harness"
RUN="$ROOT/.tmp/par08b-run"
EVID="D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence"
ELECTRON="D:/Atlas/node_modules/.bin/electron"

rm -rf "$RUN"
rm -f "$EVID"/par08-b-electron-*
mkdir -p "$RUN/data-root/data" "$RUN/userdata-window1" "$RUN/userdata-window2"

# Initial cross-device file: one legacy-shaped action map shared by both windows.
printf '{\n  "palette": ["Ctrl+K"],\n  "newTask": ["Ctrl+N"]\n}\n' > "$RUN/data-root/data/keybindings.json"
cp "$RUN/data-root/data/keybindings.json" "$EVID/par08-b-electron-initial-keybindings.json"

PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
echo "backend port: $PORT"

cd "$HARNESS" || exit 3
ATLAS_DATA_DIR="$RUN/data-root" PYTHONPATH="$ROOT/core" \
  python "$HARNESS/backend_app.py" --port "$PORT" > "$EVID/par08-b-electron-backend.log" 2>&1 &
BACKEND_PID=$!

READY=0
for _ in $(seq 1 150); do
  if curl -fsS "http://127.0.0.1:$PORT/api/u6/keybindings" > "$RUN/backend-baseline.json" 2>/dev/null; then
    READY=1
    break
  fi
  sleep 0.2
done
echo "backend ready: $READY"
if [ "$READY" != "1" ]; then
  echo "backend did not start" | tee "$EVID/par08-b-electron-run.log"
  kill "$BACKEND_PID" 2>/dev/null
  exit 4
fi
cp "$RUN/backend-baseline.json" "$EVID/par08-b-electron-baseline-get.json"

COMMON_W2=(--role=window2 --url="http://127.0.0.1:$PORT/" --out="$EVID" --run="$RUN")
COMMON_W1=(--role=window1 --url="http://127.0.0.1:$PORT/" --out="$EVID" --run="$RUN")

# Window 2 mounts first and reads revision 1; window 1 then saves action A.
"$ELECTRON" --user-data-dir="$RUN/userdata-window2" "$HARNESS/driver.cjs" "${COMMON_W2[@]}" \
  > "$EVID/par08-b-electron-window2-driver.log" 2>&1 &
W2_PID=$!
sleep 1
"$ELECTRON" --user-data-dir="$RUN/userdata-window1" "$HARNESS/driver.cjs" "${COMMON_W1[@]}" \
  > "$EVID/par08-b-electron-window1-driver.log" 2>&1 &
W1_PID=$!

wait "$W1_PID"; W1_EXIT=$?
wait "$W2_PID"; W2_EXIT=$?
echo "window1 exit: $W1_EXIT"
echo "window2 exit: $W2_EXIT"

kill "$BACKEND_PID" 2>/dev/null
wait "$BACKEND_PID" 2>/dev/null
BACKEND_EXIT=$?

cp "$RUN/data-root/data/keybindings.json" "$EVID/par08-b-electron-keybindings-after.json"
cp "$RUN/backend-baseline.json" "$EVID/par08-b-electron-baseline-get.json" 2>/dev/null

python - "$PORT" "$W1_EXIT" "$W2_EXIT" "$BACKEND_EXIT" "$EVID" <<'PY'
import json, pathlib, sys
port, w1, w2, backend, evidence = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), pathlib.Path(sys.argv[5])
after = json.loads((evidence / "par08-b-electron-keybindings-after.json").read_text(encoding="utf-8"))
summary = {
    "backend_port": int(port),
    "window1_exit": w1,
    "window2_exit": w2,
    "backend_exit_after_sigterm": backend,
    "final_palette": after.get("palette"),
    "final_newtask": after.get("newTask"),
    "final_revision_sha256": None,
    "result": "PASS" if w1 == 0 and w2 == 0 and after.get("palette") == ["Ctrl+Alt+U"] and after.get("newTask") == ["Ctrl+Alt+N"] else "FAIL",
}
import hashlib
summary["final_revision_sha256"] = hashlib.sha256((evidence / "par08-b-electron-keybindings-after.json").read_bytes()).hexdigest()
(evidence / "par08-b-electron-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
SUMMARY_EXIT=$?

{
  echo "date: $(date -Iseconds)"
  echo "worktree: $ROOT"
  echo "branch: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  echo "head: $(git -C "$ROOT" rev-parse HEAD)"
  echo "panel_sha256: $(sha256sum "$ROOT/frontend/src/renderer/pages/ShortcutsPanel.tsx" | cut -d' ' -f1)"
  echo "service_sha256: $(sha256sum "$ROOT/frontend/src/renderer/services/keybindings.ts" | cut -d' ' -f1)"
  echo "bundle_sha256: $(sha256sum "$HARNESS/bundle.js" | cut -d' ' -f1)"
  echo "backend: uvicorn host app with atlas.api.u6_router, ATLAS_DATA_DIR=$RUN/data-root"
  echo "port: $PORT"
  echo "electron: $($ELECTRON --version)"
  echo "window1 argv: --user-data-dir=$RUN/userdata-window1 driver.cjs ${COMMON_W1[*]}"
  echo "window2 argv: --user-data-dir=$RUN/userdata-window2 driver.cjs ${COMMON_W2[*]}"
  echo "window1 exit: $W1_EXIT"
  echo "window2 exit: $W2_EXIT"
  echo "summary exit: $SUMMARY_EXIT"
} > "$EVID/par08-b-electron-run.log"

if [ "$W1_EXIT" != "0" ] || [ "$W2_EXIT" != "0" ] || [ "$SUMMARY_EXIT" != "0" ]; then
  exit 1
fi
exit 0