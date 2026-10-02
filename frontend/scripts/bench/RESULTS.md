# 长会话性能基准（ATLAS-C6 / W4）

测量日期：2026-10-03。硬件：本机开发机（Windows，硬件噪声如实呈现，未做-pass 粉饰）。

## 方法

- `scripts/bench/seed_long.py`：用 `core/.venv/Scripts/python.exe` + 隔离的 `ATLAS_DATA_DIR`（临时目录），
  复用 `atlas.memory.MemoryStore` 建库并直插 2 个会话 × 各 2000 条消息（user/assistant 交替，
  每 40 条左右一条 ~15KB 的带代码块长回复，用于压测 markdown + 高亮渲染）。不碰 8765 端口和用户数据。
- `scripts/bench/long-session.mjs`：起隔离后端（uvicorn，随机空闲端口）+ vite dev（5173，后端
  OriginGuard 只信任 5173/4173 这两个开发来源），用 playwright-core 驱动系统 Edge（无头，1440×900）。
- 「interactive」标准：点开侧边栏的 2000 条会话后，store 里已载入 100 条（一页）+ 虚拟列表已画出消息 + 输入框可聚焦。
- 流式平滑度：300 条 `message.delta` 以 ~100Hz 灌进真实 store（走 eventBuffer 合流 → React），
  用 requestAnimationFrame 采样整段帧间隔。
- `vite build` 已另行验证通过（14.9s，仅有既存的大 chunk 警告）。

## 结果（多轮运行，环境相同）

| 指标 | 目标 | 实测（3 次运行） |
| --- | --- | --- |
| 打开 2000 条会话 → interactive | < 1s | **146–311ms**（280 / 275 / 290ms 上下） |
| 两个大会话之间切换 | < 300ms | **50–347ms**；冷切换（第一次到未缓存的会话，含取数）约 250–350ms，缓存后 50–210ms |
| 流式 300 条 delta 的帧间隔（p50 / p95 / max） | 无持续卡顿 | p50 **7–12ms**，p95 **12–20ms**，max **20–74ms**（偶发一帧 GC/翻页停顿，无持续掉帧） |
| 滚动到顶自动翻页 | 可用 | 100 → 200 条，视口锚定不跳动（scrollTop 保持在中部而不是跳 0） |
| 流式后 heap | — | 48–119 MB（含 dev server 开销；vite dev 未压缩） |

## 瓶颈与结论

1. 打开/切换的剩余成本主要是**首次取数 + 100 条全量 ReactMarkdown 解析**（每条含代码块时 rehype-highlight
   最贵）。冷切换偶尔 ~350ms 就是这一下；虚拟化后不再渲染整表，缓存过就只剩 50–150ms。
2. 流式已由 eventBuffer 把 React 提交压到 ~12.5Hz，帧间隔 p95 < 20ms；max 偶发 1 停顿来自
   翻页插入（firstItemIndex 锚定）或 GC，非持续 jank。
3. `run.events` 截断在 800 条 + 步骤文本截断 4000 字符，长任务内存不再无界增长。

## 已知限制（如实）

- 切换会话的第一次（未命中缓存）约 300–350ms，压不到 300ms 以内；后续切换达标。可通过提高缓存上限再换。
- 恢复滚动存档后，Virtuoso 的 `startReached` 在高度估算收敛期间可能不触发一次自动翻页
  （列表仍在顶部时再滚一下即恢复）；显式的「载入更早的消息」按钮始终可用。
- TimelineNav（不在 W4 所有权内）用 DOM 查询 `[data-message-role]` 收集导航点；虚拟化后只有可见行
  在 DOM 里，导航点覆盖范围随之受限。若要恢复全量时间线，需要改为从 store 数据生成（留给主代理）。
- 流式回复用纯文本渲染（保留换行），`message.completed` 后切换回完整 Markdown 渲染——
  落定前粗体/代码块不着色，是刻意的性能取舍。

## 复现

```bash
cd frontend
node scripts/bench/long-session.mjs
```
