/*
 * Collapsed trigger adapted from zai-org/ZCode packages/ui/src/components/ai-elements/reasoning.tsx
 * (itself derived from vercel/ai-elements reasoning.tsx, Apache-2.0): one line with a sweeping
 * "思考中" label and the newest thought rolling in beside it; "已思考 · N 秒" when done.
 * Expanded panel adapted from assistant-ui elements/reasoning.tsx (MIT): a height-capped box that
 * follows the newest text while streaming, pauses following when the reader scrolls up, and fades
 * at the top edge.
 */
import { useEffect, useRef, useState } from 'react';
import { Brain, ChevronRight, ClipboardCopy } from 'lucide-react';
import { cn } from '../ui/cn';

/** Last non-empty line of the streamed thinking (ZCode resolveReasoningStreamingSummary). */
function latestLine(text: string): string {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index].trim();
    if (line) return line.replace(/\*\*/g, '');
  }
  return '';
}

function seconds(startedAt?: string, endedAt?: string): number | null {
  if (!startedAt || !endedAt) return null;
  const span = Date.parse(endedAt) - Date.parse(startedAt);
  return Number.isFinite(span) && span >= 0 ? Math.max(1, Math.ceil(span / 1000)) : null;
}

export default function ReasoningBlock({ text, streaming, startedAt, endedAt, truncated }: {
  text: string;
  streaming: boolean;
  startedAt?: string;
  endedAt?: string;
  truncated?: boolean;
}) {
  // Collapsed by default (ZCode); the reader's own toggle always wins over the automatic state.
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? false;
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState(false);
  const rollRef = useRef<HTMLSpanElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Live seconds only while streaming and visible; the finished duration comes from event timestamps.
  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [streaming]);
  const liveSeconds = startedAt ? Math.max(1, Math.ceil((now - Date.parse(startedAt)) / 1000)) : null;
  const doneSeconds = seconds(startedAt, endedAt);

  // Keep the rolling one-line summary scrolled to its end so the newest words stay visible (ZCode).
  const line = streaming && !open ? latestLine(text) : '';
  useEffect(() => {
    const roll = rollRef.current;
    if (roll) roll.scrollLeft = roll.scrollWidth;
  }, [line]);

  // Follow the bottom while streaming unless the reader scrolled up (assistant-ui ReasoningText).
  useEffect(() => {
    if (!open || !streaming) return;
    const scrollEl = scrollRef.current;
    const contentEl = contentRef.current;
    if (!scrollEl || !contentEl) return;
    let pinned = true;
    let lastTop = scrollEl.scrollTop;
    let lastHeight = scrollEl.scrollHeight;
    const atBottom = () => Math.abs(scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight) <= 2;
    const pin = () => { if (pinned) scrollEl.scrollTop = scrollEl.scrollHeight; };
    const onScroll = () => {
      if (atBottom()) pinned = true;
      else if (scrollEl.scrollTop < lastTop && scrollEl.scrollHeight === lastHeight) pinned = false;
      lastTop = scrollEl.scrollTop;
      lastHeight = scrollEl.scrollHeight;
    };
    pin();
    scrollEl.addEventListener('scroll', onScroll);
    const observer = new ResizeObserver(pin);
    observer.observe(contentEl);
    return () => { scrollEl.removeEventListener('scroll', onScroll); observer.disconnect(); };
  }, [open, streaming]);

  const label = streaming
    ? <span className="text-shimmer font-medium">思考中{open && liveSeconds ? ` ${liveSeconds} 秒` : ''}</span>
    : <span className="text-fg-3">已思考{doneSeconds ? ` · ${doneSeconds} 秒` : ''}</span>;

  return <div className="my-2 ml-10 min-w-0">
    <button type="button" onClick={() => setUserOpen(!open)} aria-expanded={open}
      className="group/reasoning flex max-w-full min-w-0 items-center gap-2 py-0.5 text-left text-[13px]">
      <Brain size={14} className="shrink-0 text-fg-3" aria-hidden="true" />
      <span className="shrink-0 whitespace-nowrap">{label}</span>
      {line && <>
        <span className="shrink-0 text-fg-3">·</span>
        <span ref={rollRef} className="min-w-0 flex-1 overflow-hidden whitespace-nowrap text-fg-2"
          style={{ WebkitMaskImage: 'linear-gradient(to right, transparent 0, black 16px)', maskImage: 'linear-gradient(to right, transparent 0, black 16px)' }}>
          <span className="inline-block min-w-max">{line}</span>
        </span>
      </>}
      <ChevronRight size={14} aria-hidden="true" className={cn('shrink-0 text-fg-3 transition-[transform,opacity]',
        open ? 'rotate-90 opacity-100' : 'opacity-0 group-hover/reasoning:opacity-100')} />
    </button>
    {open && <div className="anim-fade relative mt-1">
      <div ref={scrollRef} className="max-h-64 overflow-y-auto pl-[22px] pr-2"
        style={{ WebkitMaskImage: 'linear-gradient(to bottom, transparent 0, black 20px)', maskImage: 'linear-gradient(to bottom, transparent 0, black 20px)' }}>
        <div ref={contentRef} className="whitespace-pre-wrap break-words pt-3 pb-1 text-[12.5px] leading-[1.75] text-fg-3">
          {text.trim()}
          {truncated && <p className="m-0 mt-2 text-[11.5px]">（思考内容过长，只保留了前 60,000 字）</p>}
        </div>
      </div>
      {!streaming && <button type="button" onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); }).catch(() => undefined);
      }} className="ml-[18px] mt-1 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-fg-3 hover:bg-hover hover:text-fg">
        <ClipboardCopy size={12} aria-hidden="true" />{copied ? '已复制' : '复制思考'}
      </button>}
    </div>}
  </div>;
}
