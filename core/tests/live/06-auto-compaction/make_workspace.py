"""Materialize scenario 06's oversized big.txt (deterministic, ~200KB / ~130k tokens)."""
import sys
from pathlib import Path

WS = Path(sys.argv[1])
TOTAL_LOG_LINES = 4000
CODE_EVERY = 160           # 25 key codes at lines 160, 320, ..., 4000
CODE_BASE = 1000           # KEY-1000 .. KEY-1024
MAGIC = "6174"

lines: list[str] = []
for index in range(1, TOTAL_LOG_LINES + 1):
    if index % CODE_EVERY == 0:
        code = f"KEY-{CODE_BASE + index // CODE_EVERY - 1}"
        lines.append(f"记录点 {index}：本段包含关键码 {code}，巡检观察到队列延迟轻微波动后恢复，"
                     "内存占用平稳，磁盘余量充足，无需人工干预，服务继续稳定运行。")
    elif index % 40 == 0:
        lines.append(f"记录行 {index}：常规巡检观察，无明显异常，内存占用平稳，"
                     "队列延迟处于正常区间，磁盘余量充足，网络抖动可以忽略，服务继续稳定运行。")
    else:
        lines.append(f"日志行 {index}：常规心跳，状态正常，无需处理。")
lines.append(f"魔数：{MAGIC}")
# The file is exactly TOTAL_LOG_LINES + 1 lines and ends with a newline.
(WS / "big.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"big.txt lines={len(lines)} bytes={(WS / 'big.txt').stat().st_size}")
