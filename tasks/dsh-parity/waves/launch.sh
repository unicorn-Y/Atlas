#!/bin/bash
# Launch one codex exec session per wave, each in its own worktree.
W=$1
case "$W" in
  W1)  ROWS="E2 E19 E25" ;;
  W2)  ROWS="E3 E4" ;;
  W3)  ROWS="E8 S9 S25" ;;
  W4)  ROWS="E11 E17" ;;
  W5)  ROWS="S4 S19 S21" ;;
  W6)  ROWS="S16 S22" ;;
  W7)  ROWS="E14 E18" ;;
  W8)  ROWS="E16" ;;
  W9)  ROWS="X2 X4 X8" ;;
  W10) ROWS="X16" ;;
  W11) ROWS="X23 X9" ;;
  W12) ROWS="D1 D2 D3" ;;
  W13) ROWS="D4 D30" ;;
  W14) ROWS="D5 D6" ;;
  W15) ROWS="D7 D8" ;;
  W16) ROWS="D10 D13 D17" ;;
  *) echo "unknown wave $W"; exit 2 ;;
esac
PORT=$((8820 + ${W#W}))
WT="D:/Atlas/.worktrees/dsh-$W"
LOG="D:/Atlas/tasks/dsh-parity/waves/logs/$W.log"
mkdir -p "D:/Atlas/tasks/dsh-parity/waves/logs"
cd "$WT" || exit 3
codex exec \
  -m gpt-6-luna \
  -c model_reasoning_effort='"high"' \
  -c approval_policy='"never"' \
  -s danger-full-access \
  -C "$WT" \
  "你是 $W 批 worker。先读 D:/Atlas/tasks/dsh-parity/WAVE-PLAN.md 和 tasks/dsh-parity/waves/RUNNER.md。你负责的 rows: $ROWS。真实模型验证用端口 $PORT。只改本 worktree 内属于你批次目录的文件。做完写 tasks/dsh-parity/waves/RESULT-$W.md 并 commit 到当前分支。不要停，不要问我。" \
  > "$LOG" 2>&1
echo "$W done exit=$?"
