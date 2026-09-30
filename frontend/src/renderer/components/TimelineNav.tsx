import { useEffect, useState, type RefObject } from 'react';
import { cn } from '../ui/cn';

type Mark = { index: number; label: string };

/** A rail of the conversation's requests along the thread's edge; click one to jump back to it. */
export default function TimelineNav({ threadRef, resetKey }: { threadRef: RefObject<HTMLDivElement>; resetKey: string }) {
  const [marks, setMarks] = useState<Mark[]>([]);
  const [current, setCurrent] = useState(-1);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;
    const bubbles = () => [...thread.querySelectorAll<HTMLElement>('[data-message-role="user"]')];
    const collect = () => setMarks((previous) => {
      const next = bubbles().map((element, index) => ({ index, label: (element.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80) }));
      return next.length === previous.length && next.every((mark, i) => mark.label === previous[i].label) ? previous : next;
    });
    // The request whose bubble is closest above the middle of the view is "where you are".
    const locate = () => {
      const middle = thread.getBoundingClientRect().top + thread.clientHeight / 2;
      let found = -1;
      bubbles().forEach((element, index) => { if (element.getBoundingClientRect().top <= middle) found = index; });
      setCurrent(found);
    };
    collect(); locate();
    const observer = new MutationObserver(() => { collect(); locate(); });
    observer.observe(thread, { childList: true, subtree: true });
    thread.addEventListener('scroll', locate, { passive: true });
    return () => { observer.disconnect(); thread.removeEventListener('scroll', locate); };
  }, [threadRef, resetKey]);

  if (marks.length < 3) return null;
  const jump = (index: number) => threadRef.current?.querySelectorAll<HTMLElement>('[data-message-role="user"]')[index]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return <nav aria-label="对话时间线" className="absolute top-1/2 right-1.5 z-10 flex max-h-[60%] -translate-y-1/2 flex-col gap-1 overflow-y-auto py-1">
    {marks.map((mark) => <button key={mark.index} onClick={() => jump(mark.index)} title={mark.label} aria-label={`跳到第 ${mark.index + 1} 条：${mark.label}`} aria-current={mark.index === current ? 'step' : undefined}
      className="group grid h-3 w-5 shrink-0 place-items-center">
      <span className={cn('block h-[3px] rounded-full transition-all', mark.index === current ? 'w-4 bg-brand' : 'w-2.5 bg-line-strong group-hover:w-4 group-hover:bg-fg-3')} />
    </button>)}
  </nav>;
}
