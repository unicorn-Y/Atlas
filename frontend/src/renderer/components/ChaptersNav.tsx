import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { ConversationMessage } from '@atlas/backend-adapter';
import type { AgentEvent } from '../../types/runtime';

type Chapter = { id: string; title: string; rowId: string; automatic?: boolean; headingIndex?: number };
const keyFor = (conversationId: string) => `atlas.chapters.${conversationId}`;

/** User-authored chapter marks in the conversation, with jump targets aligned to MessageThread rows. */
export default function ChaptersNav({ conversationId, threadRef, history, events }: {
  conversationId: string; threadRef: RefObject<HTMLDivElement | null>; history: ConversationMessage[]; events: AgentEvent[];
}) {
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const handledEvents = useRef(new Set<string>());
  useEffect(() => {
    try {
      const value: unknown = JSON.parse(localStorage.getItem(keyFor(conversationId)) ?? '[]');
      setChapters(Array.isArray(value) ? value.flatMap((item) => item && typeof item.id === 'string' && typeof item.title === 'string'
        ? [{ id: item.id, title: item.title, rowId: typeof item.rowId === 'string' ? item.rowId : typeof item.messageId === 'string' ? `h-${item.messageId}` : '' }].filter((chapter) => chapter.rowId)
        : []) : []);
    }
    catch { setChapters([]); }
  }, [conversationId]);
  const automatic = useMemo(() => history.flatMap((message) => {
    if (message.role !== 'assistant') return [];
    const headings = [...message.content.matchAll(/^#{1,3}\s+(.+)\s*$/gm)].slice(0, 12);
    return headings.map((match, index) => ({ id: `auto-${message.id}-${index}`, title: match[1].trim().slice(0, 80), rowId: `h-${message.id}`, automatic: true, headingIndex: index }));
  }).slice(-40), [history]);
  const allChapters = useMemo(() => [...chapters, ...automatic], [chapters, automatic]);
  const resolved = useMemo(() => allChapters.filter((chapter) => history.some((message) => `h-${message.id}` === chapter.rowId)
    || [...(threadRef.current?.querySelectorAll<HTMLElement>('[data-conversation-search-row]') ?? [])]
      .some((row) => row.dataset.conversationSearchRow === chapter.rowId)), [allChapters, history, threadRef]);
  useEffect(() => { const handle = (event: Event) => {
    const detail = (event as CustomEvent<{ title?: string; runId?: string; sequence?: number }>).detail;
    const title = detail?.title?.trim();
    const rows = [...(threadRef.current?.querySelectorAll<HTMLElement>('[data-conversation-search-row]') ?? [])];
    const last = history.at(-1);
    const runRows = detail?.runId ? rows.filter((row) => row.dataset.conversationSearchRow?.startsWith(`t-${detail.runId}:`)) : [];
    const priorRunRows = runRows.filter((row) => Number(row.dataset.conversationSearchRow?.split(':').at(-1)) <= (detail?.sequence ?? Number.MAX_SAFE_INTEGER));
    const rowId = last ? `h-${last.id}` : priorRunRows.at(-1)?.dataset.conversationSearchRow ?? rows.at(-1)?.dataset.conversationSearchRow;
    if (!title || !rowId) return;
    const chapter = { id: crypto.randomUUID(), title: title.slice(0, 80), rowId };
    setChapters((current) => {
      if (current.some((item) => item.title === chapter.title && item.rowId === chapter.rowId)) return current;
      const next = [...current, chapter]; try { localStorage.setItem(keyFor(conversationId), JSON.stringify(next)); } catch { /* private storage */ } return next;
    });
  };
    window.addEventListener('atlas:add-chapter', handle); return () => window.removeEventListener('atlas:add-chapter', handle);
  }, [conversationId, history]);
  useEffect(() => {
    for (const event of events) {
      if (event.type !== 'chapter.marked' || handledEvents.current.has(event.id) || typeof event.data.title !== 'string') continue;
      handledEvents.current.add(event.id);
      window.dispatchEvent(new CustomEvent('atlas:add-chapter', { detail: { title: event.data.title, runId: event.runId, sequence: event.sequence } }));
    }
  }, [events]);
  if (!resolved.length) return null;
  return <nav aria-label="对话章节目录" className="absolute right-1 top-1/2 z-10 flex max-h-[60%] -translate-y-1/2 flex-col gap-1 overflow-y-auto rounded-lg border border-line bg-panel/95 p-2 shadow-lg">
    <span className="px-1 text-[10px] font-semibold text-fg-3">目录</span>{resolved.map((chapter) => <button key={chapter.id} title={`${chapter.automatic ? '自动目录' : '手动章节'}：${chapter.title}`} onClick={() => {
    const thread = threadRef.current;
    const row = [...(thread?.querySelectorAll<HTMLElement>('[data-conversation-search-row]') ?? [])]
      .find((element) => element.dataset.conversationSearchRow === chapter.rowId);
    const target = chapter.automatic && row
      ? row.querySelectorAll<HTMLElement>('h1, h2, h3')[chapter.headingIndex ?? 0] ?? row
      : row;
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }} className="max-w-36 truncate rounded-md px-2 py-1 text-left text-[11.5px] text-fg-2 hover:bg-hover">{chapter.automatic && <span aria-hidden="true" className="mr-1 text-brand">#</span>}{chapter.title}</button>)}
  </nav>;
}
