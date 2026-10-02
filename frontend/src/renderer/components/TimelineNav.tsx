import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { ConversationMessage } from '@atlas/backend-adapter';
import { cn } from '../ui/cn';
import type { TimelineItem } from './timeline';

export interface TimelineNavMark { id: string; label: string; rowIndex: number }

/** Virtuoso 的每个已渲染行都带 data-index；量出这些行在内容里的坐标，未渲染的行按邻近行高内插。 */
function measure(thread: HTMLElement): Map<number, number> {
  const origin = thread.getBoundingClientRect().top;
  const scrollTop = thread.scrollTop;
  const map = new Map<number, number>();
  for (const element of thread.querySelectorAll<HTMLElement>('[data-index]')) {
    const index = Number(element.getAttribute('data-index'));
    if (Number.isInteger(index)) map.set(index, element.getBoundingClientRect().top - origin + scrollTop);
  }
  return map;
}

/** 目标行的内容坐标：渲染过的行直接量，没渲染的按上下最近两行线性内插/外推。 */
function estimateAt(map: Map<number, number>, index: number): number | null {
  const direct = map.get(index);
  if (direct !== undefined) return direct;
  const entries = [...map.entries()].sort((a, b) => a[0] - b[0]);
  if (!entries.length) return null;
  const perRow = (a: [number, number], b: [number, number]) => Math.max(24, Math.abs(b[1] - a[1]) / Math.max(1, Math.abs(b[0] - a[0])));
  const lower = [...entries].reverse().find(([value]) => value < index);
  const upper = entries.find(([value]) => value > index);
  if (lower && upper) {
    const [i0, o0] = lower;
    const [i1, o1] = upper;
    return o0 + (o1 - o0) * ((index - i0) / (i1 - i0));
  }
  if (lower) {
    const previous = entries.filter(([value]) => value < lower[0]).pop();
    const step = previous ? perRow(previous, lower) : 90;
    return lower[1] + step * (index - lower[0]);
  }
  const [i1, o1] = entries[0];
  const next = entries.find(([value]) => value > i1);
  const step = next ? perRow(entries[0], next) : 90;
  return Math.max(0, o1 - step * (i1 - index));
}

/**
 * 对话右侧的请求导航点。请求列表从会话数据推导（历史消息 + 当前运行的时间线），
 * 不再查询 DOM——虚拟列表只渲染可见行，DOM 收集会漏掉大半请求。
 */
export default function TimelineNav({ threadRef, resetKey, history, items, hasEarlier, truncatedCount, loading }: {
  threadRef: RefObject<HTMLDivElement | null>;
  resetKey: string;
  /** App 已排好序的历史消息（含分叉备注、去掉当前运行那一轮），与 MessageThread 收到的完全一致。 */
  history: ConversationMessage[];
  /** 当前运行的时间线（buildTimeline 的产物）。 */
  items: TimelineItem[];
  /** 列表头部的占位行：载入更早、已折叠早期事件。 */
  hasEarlier: boolean;
  truncatedCount: number;
  loading: boolean;
}) {
  const marks = useMemo<TimelineNavMark[]>(() => {
    const collected: TimelineNavMark[] = [];
    let rowIndex = 0;
    if (hasEarlier) rowIndex += 1;
    if (truncatedCount > 0) rowIndex += 1;
    for (const message of history) {
      if (message.role === 'user') collected.push({ id: `h-${message.id}`, label: message.content.replace(/\s+/g, ' ').slice(0, 80), rowIndex });
      rowIndex += 1;
    }
    // MessageThread 在两边都空时插一个空状态行。
    if (!history.length && !items.length && !loading) rowIndex += 1;
    for (const item of items) {
      if (item.kind === 'user') collected.push({ id: item.id, label: item.content.replace(/\s+/g, ' ').slice(0, 80), rowIndex });
      rowIndex += 1;
    }
    return collected;
  }, [history, items, hasEarlier, truncatedCount, loading]);
  const marksRef = useRef(marks);
  marksRef.current = marks;
  const [current, setCurrent] = useState(-1);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread || !marksRef.current.length) { setCurrent(-1); return; }
    // 视口中线以上的最近一条请求，就是「你在哪儿」。
    const locate = () => {
      const map = measure(thread);
      const center = thread.scrollTop + thread.clientHeight / 2;
      let found = -1;
      marksRef.current.forEach((mark, index) => {
        const at = estimateAt(map, mark.rowIndex);
        if (at !== null && at <= center) found = index;
      });
      setCurrent(found);
    };
    locate();
    thread.addEventListener('scroll', locate, { passive: true });
    const observer = new MutationObserver(locate);
    observer.observe(thread, { childList: true, subtree: true });
    return () => { thread.removeEventListener('scroll', locate); observer.disconnect(); };
  }, [threadRef, resetKey, marks, history.length, items.length]);

  if (marks.length < 3) return null;
  const jump = (mark: TimelineNavMark) => {
    const thread = threadRef.current;
    if (!thread) return;
    const top = estimateAt(measure(thread), mark.rowIndex);
    if (top === null) return;
    thread.scrollTo({ top: Math.max(0, top - 16), behavior: 'smooth' });
  };
  return <nav aria-label="对话时间线" className="absolute top-1/2 right-1.5 z-10 flex max-h-[60%] -translate-y-1/2 flex-col gap-1 overflow-y-auto py-1">
    {marks.map((mark, index) => <button key={mark.id} onClick={() => jump(mark)} title={mark.label} aria-label={`跳到第 ${index + 1} 条：${mark.label}`} aria-current={index === current ? 'step' : undefined}
      className="group grid h-3 w-5 shrink-0 place-items-center">
      <span className={cn('block h-[3px] rounded-full transition-all', index === current ? 'w-4 bg-brand' : 'w-2.5 bg-line-strong group-hover:w-4 group-hover:bg-fg-3')} />
    </button>)}
  </nav>;
}
