#!/bin/bash
W=$1
case "$W" in
  V1)  ROWS="E2 E19 E25" ;;
  V2)  ROWS="E3 E4" ;;
  V3)  ROWS="E8 S9 S25" ;;
  V4)  ROWS="S4 S19 S21" ;;
  V5)  ROWS="X2 X4 X8 X9" ;;
  V6)  ROWS="X22 D13" ;;
  V7)  ROWS="E14 E18" ;;
  V8)  ROWS="D1 D2 D3 D7" ;;
  V9)  ROWS="D4 D5 D6" ;;
  V10) ROWS="D8 D10 D17" ;;
  *) echo "unknown $W"; exit 2 ;;
esac
PORT=$((8830 + ${W#V}))
WT="D:/Atlas/.worktrees/dsh2-$W"
mkdir -p "D:/Atlas/tasks/dsh-parity/waves/logs"
cd "$WT" || exit 3
codex exec \
  -m gpt-6-luna \
  -c model_reasoning_effort='"high"' \
  -c approval_policy='"never"' \
  -s danger-full-access \
  -C "$WT" \
  "你是 $W 批 worker（WAVE 2）。先读 D:/Atlas/tasks/dsh-parity/WAVE2-PLAN.md。你负责的 rows: $ROWS。**关键：本轮你有权改该能力跨越的所有目录**，不要因为目录边界而拒绝接线。真实模型验证必须用 WAVE2-PLAN.md 里写的 Atlas 通道（deepseek-v4.1-flash + http_proxy=127.0.0.1:7897），端口 $PORT。做完写 tasks/dsh-parity/waves/RESULT2-$W.md 并 commit。不要停。" \
  > "D:/Atlas/tasks/dsh-parity/waves/logs/$W.log" 2>&1
echo "$W exit=$?"
