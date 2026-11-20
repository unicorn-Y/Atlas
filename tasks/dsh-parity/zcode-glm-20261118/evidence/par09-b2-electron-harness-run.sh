#!/usr/bin/env bash
# PAR-09-B2 real dual-window acceptance: three independent scenarios, each with
# a temporary uvicorn hosting the worktree u6 router and two isolated Electron
# processes mounting the actual worktree ShortcutsPanel.
#
#   missing      initial keybindings.json absent
#   existing     initial keybindings.json present (different-action replay)
#   same-action  both windows edit palette, window2 resolves per action
set -u

ROOT="D:/Atlas/.worktrees/zcode-exec06-keybindings-cas"
HARNESS="$ROOT/.tmp/par09b2-harness"
RUN="$ROOT/.tmp/par09b2-run"
EVID="D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence"
ELECTRON="D:/Atlas/node_modules/.bin/electron"
ESBUILD="D:/Atlas/node_modules/.bin/esbuild"

rm -rf "$RUN"
rm -f "$EVID"/par09-b2-electron-*
mkdir -p "$EVID"

cd "$HARNESS" || exit 3
"$ESBUILD" harness.tsx --bundle --format=iife --jsx=automatic \
  --define:process.env.NODE_ENV='"production"' --outfile=bundle.js \
  > "$EVID/par09-b2-electron-esbuild.log" 2>&1
BUILD_EXIT=$?
echo "esbuild exit: $BUILD_EXIT"
if [ "$BUILD_EXIT" != "0" ]; then
  exit "$BUILD_EXIT"
fi

OVERALL_EXIT=0
SCENARIOS=(missing existing same-action)
SCENARIO_RESULTS=()

for SCENARIO in "${SCENARIOS[@]}"; do
  SRUN="$RUN/$SCENARIO"
  mkdir -p "$SRUN/data-root/data" "$SRUN/userdata-window1" "$SRUN/userdata-window2"

  if [ "$SCENARIO" != "missing" ]; then
    printf '{\n  "palette": ["Ctrl+K"],\n  "newTask": ["Ctrl+N"]\n}\n' > "$SRUN/data-root/data/keybindings.json"
    cp "$SRUN/data-root/data/keybindings.json" "$EVID/par09-b2-electron-$SCENARIO-initial-keybindings.json"
  fi

  PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
  echo "[$SCENARIO] backend port: $PORT"

  ATLAS_DATA_DIR="$SRUN/data-root" PYTHONPATH="$ROOT/core" \
    python "$HARNESS/backend_app.py" --port "$PORT" > "$EVID/par09-b2-electron-$SCENARIO-backend.log" 2>&1 &
  BACKEND_PID=$!

  READY=0
  for _ in $(seq 1 150); do
    if curl -fsS "http://127.0.0.1:$PORT/api/u6/keybindings" > "$SRUN/baseline-get.json" 2>/dev/null; then
      READY=1
      break
    fi
    sleep 0.2
  done
  echo "[$SCENARIO] backend ready: $READY"
  if [ "$READY" != "1" ]; then
    echo "[$SCENARIO] backend did not start"
    kill "$BACKEND_PID" 2>/dev/null
    OVERALL_EXIT=4
    SCENARIO_RESULTS+=("{\"scenario\": \"$SCENARIO\", \"result\": \"FAIL\", \"reason\": \"backend did not start\"}")
    continue
  fi
  cp "$SRUN/baseline-get.json" "$EVID/par09-b2-electron-$SCENARIO-baseline-get.json"

  COMMON=(--scenario="$SCENARIO" --url="http://127.0.0.1:$PORT/" --out="$EVID" --run="$SRUN")

  "$ELECTRON" --user-data-dir="$SRUN/userdata-window2" "$HARNESS/driver.cjs" --role=window2 "${COMMON[@]}" \
    > "$EVID/par09-b2-electron-$SCENARIO-window2-driver.log" 2>&1 &
  W2_PID=$!
  sleep 1
  "$ELECTRON" --user-data-dir="$SRUN/userdata-window1" "$HARNESS/driver.cjs" --role=window1 "${COMMON[@]}" \
    > "$EVID/par09-b2-electron-$SCENARIO-window1-driver.log" 2>&1 &
  W1_PID=$!

  wait "$W1_PID"; W1_EXIT=$?
  wait "$W2_PID"; W2_EXIT=$?
  echo "[$SCENARIO] window1 exit: $W1_EXIT; window2 exit: $W2_EXIT"

  kill "$BACKEND_PID" 2>/dev/null
  wait "$BACKEND_PID" 2>/dev/null
  BACKEND_EXIT=$?

  if [ -f "$SRUN/data-root/data/keybindings.json" ]; then
    cp "$SRUN/data-root/data/keybindings.json" "$EVID/par09-b2-electron-$SCENARIO-keybindings-after.json"
  fi

  VALIDATE_EXIT=0
  python - "$SCENARIO" "$W1_EXIT" "$W2_EXIT" "$BACKEND_EXIT" "$EVID" <<'PY' || VALIDATE_EXIT=$?
import hashlib, json, pathlib, sys

scenario, w1, w2, backend, evidence = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), pathlib.Path(sys.argv[5])
prefix = f"par09-b2-electron-{scenario}"

def load(name):
    path = evidence / f"{prefix}-{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

after_path = evidence / f"{prefix}-keybindings-after.json"
after = json.loads(after_path.read_text(encoding="utf-8")) if after_path.exists() else {}
w2_409 = load("window2-409")
w2_retry = load("window2-retry")
w2_replay = load("window2-replay-conflict")
w2_resolved = load("window2-resolved")
w1_after = load("window1-after")
backend_log = (evidence / f"{prefix}-backend.log").read_text(encoding="utf-8", errors="replace")

problems = []
def expect(condition, message):
    if not condition:
        problems.append(message)

expect(w1 == 0, f"window1 exit {w1}")
expect(w2 == 0, f"window2 exit {w2}")
expect(w2_409 is not None and w2_409.get("conflict"), "window2 never showed the 409 banner")
expect(w2_409 is not None and isinstance(w2_409.get("server", {}).get("revision"), str), "server had no revision after window1 save")

if scenario in ("missing", "existing"):
    expect(after.get("palette") == ["Ctrl+Alt+U"], f"final palette {after.get('palette')}")
    expect(after.get("newTask") == ["Ctrl+Alt+N"], f"final newTask {after.get('newTask')}")
    expect(after.get("settings") == ["Ctrl+,"], f"final settings {after.get('settings')}")
    expect(w2_retry is not None, "missing window2-retry snapshot")
    if w2_retry:
        expect(not w2_retry.get("conflict"), "conflict banner still visible after retry")
        expect(not w2_retry.get("replayConflict"), f"unexpected replay conflict rows: {w2_retry.get('replayConflict')}")
        expect(w2_retry.get("conflictRows") == [], f"unexpected per-action rows: {w2_retry.get('conflictRows')}")
        expect("其他窗口的修改已保留" in (w2_retry.get("status") or ""), f"retry status {w2_retry.get('status')!r}")
    expect(w1_after is not None, "missing window1-after snapshot")
    if w1_after:
        expect(w1_after.get("server", {}).get("bindings", {}).get("palette") == ["Ctrl+Alt+U"], "window1 did not see its palette in the file")
        expect(w1_after.get("server", {}).get("bindings", {}).get("newTask") == ["Ctrl+Alt+N"], "window1 did not see window2's newTask in the file")
else:
    expect(after.get("palette") == ["Ctrl+Alt+O"], f"same-action final palette {after.get('palette')}")
    expect(after.get("newTask") == ["Ctrl+N"], f"same-action final newTask {after.get('newTask')}")
    expect(w2_replay is not None, "missing window2-replay-conflict snapshot")
    if w2_replay:
        rows = w2_replay.get("conflictRows") or []
        expect([row.get("action") for row in rows] == ["palette"], f"conflict rows {rows}")
        expect(w2_replay.get("server", {}).get("bindings", {}).get("palette") == ["Ctrl+Alt+U"], "file changed before the user chose")
    expect(w2_resolved is not None, "missing window2-resolved snapshot")
    if w2_resolved:
        expect(not w2_resolved.get("conflict"), "conflict banner visible after resolving")
        expect("已按选择保存" in (w2_resolved.get("status") or ""), f"resolved status {w2_resolved.get('status')!r}")
        expect(w2_resolved.get("server", {}).get("bindings", {}).get("palette") == ["Ctrl+Alt+O"], "file palette is not window2's local value")

put_200 = backend_log.count('PUT /api/u6/keybindings HTTP/1.1" 200')
put_409 = backend_log.count('PUT /api/u6/keybindings HTTP/1.1" 409')
expect(put_200 == 2, f"expected two 200 PUTs in backend log, saw {put_200}")
expect(put_409 == 1, f"expected one 409 PUT in backend log, saw {put_409}")

summary = {
    "scenario": scenario,
    "window1_exit": w1,
    "window2_exit": w2,
    "backend_exit_after_sigterm": backend,
    "final_bindings": after,
    "final_revision_sha256": hashlib.sha256(after_path.read_bytes()).hexdigest() if after_path.exists() else None,
    "backend_put_200": put_200,
    "backend_put_409": put_409,
    "problems": problems,
    "result": "PASS" if not problems else "FAIL",
}
(evidence / f"{prefix}-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
sys.exit(0 if not problems else 1)
PY

  echo "[$SCENARIO] validate exit: $VALIDATE_EXIT"
  {
    echo "scenario: $SCENARIO"
    echo "date: $(date -Iseconds)"
    echo "worktree: $ROOT"
    echo "branch: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
    echo "head: $(git -C "$ROOT" rev-parse HEAD)"
    echo "panel_sha256: $(sha256sum "$ROOT/frontend/src/renderer/pages/ShortcutsPanel.tsx" | cut -d' ' -f1)"
    echo "service_sha256: $(sha256sum "$ROOT/frontend/src/renderer/services/keybindings.ts" | cut -d' ' -f1)"
    echo "bundle_sha256: $(sha256sum "$HARNESS/bundle.js" | cut -d' ' -f1)"
    echo "backend: uvicorn host app with atlas.api.u6_router, ATLAS_DATA_DIR=$SRUN/data-root"
    echo "port: $PORT"
    echo "electron: $($ELECTRON --version)"
    echo "window1 argv: --user-data-dir=$SRUN/userdata-window1 driver.cjs --role=window1 ${COMMON[*]}"
    echo "window2 argv: --user-data-dir=$SRUN/userdata-window2 driver.cjs --role=window2 ${COMMON[*]}"
    echo "window1 exit: $W1_EXIT"
    echo "window2 exit: $W2_EXIT"
    echo "validate exit: $VALIDATE_EXIT"
  } > "$EVID/par09-b2-electron-$SCENARIO-run.log"

  RESULT="PASS"
  if [ "$W1_EXIT" != "0" ] || [ "$W2_EXIT" != "0" ] || [ "$VALIDATE_EXIT" != "0" ]; then
    RESULT="FAIL"
    OVERALL_EXIT=1
  fi
  SCENARIO_RESULTS+=("$(cat "$EVID/par09-b2-electron-$SCENARIO-summary.json" 2>/dev/null || echo "{\"scenario\": \"$SCENARIO\", \"result\": \"$RESULT\"}")")
done

python - "$EVID" "${SCENARIO_RESULTS[@]}" <<'PY'
import json, pathlib, sys
evidence = pathlib.Path(sys.argv[1])
entries = [json.loads(item) for item in sys.argv[2:]]
overall = {
    "result": "PASS" if entries and all(item.get("result") == "PASS" for item in entries) else "FAIL",
    "scenarios": entries,
}
(evidence / "par09-b2-electron-summary.json").write_text(json.dumps(overall, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(overall, ensure_ascii=False, indent=2))
PY
SUMMARY_EXIT=$?
echo "overall summary exit: $SUMMARY_EXIT"

cp "$HARNESS/backend_app.py" "$EVID/par09-b2-electron-harness-backend_app.py"
cp "$HARNESS/driver.cjs" "$EVID/par09-b2-electron-harness-driver.cjs"
cp "$HARNESS/harness.tsx" "$EVID/par09-b2-electron-harness.tsx"
cp "$HARNESS/index.html" "$EVID/par09-b2-electron-harness-index.html"
cp "$HARNESS/run_electron.sh" "$EVID/par09-b2-electron-harness-run.sh"

if [ "$OVERALL_EXIT" != "0" ] || [ "$SUMMARY_EXIT" != "0" ]; then
  exit 1
fi
if grep -q '"result": "FAIL"' "$EVID/par09-b2-electron-summary.json" 2>/dev/null; then
  exit 1
fi
exit 0