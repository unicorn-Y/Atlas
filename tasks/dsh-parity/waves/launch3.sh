#!/bin/bash
W=$1; ROWS=$2; PORT=$3; WT="$4"
cd "$WT" || exit 3
codex exec -m gpt-6-luna -c model_reasoning_effort='"high"' \
  -c approval_policy='"never"' -s danger-full-access -C "$WT" \
  "你是 $W 批负责人。先读 D:/Atlas/tasks/dsh-parity/waves/W3-SESSION.md 和 D:/Atlas/tasks/dsh-parity/WAVE3-PLAN.md。
你负责的 rows: $ROWS。工作目录: $WT。真实模型端口: $PORT。
**必须 spawn 2-4 个子代理并行做子任务**，不要自己串行全干。
开工先输出「子任务拆分 + 每个子任务的文件清单」，然后分派、验收、写 RESULT3-$W.md、commit。
不要停，不要问我。" > "D:/Atlas/tasks/dsh-parity/waves/logs3-$W.log" 2>&1
echo "$W exit=$?"
