import { useEffect, useRef, useState } from 'react';
import { ArrowLeftRight, X } from 'lucide-react';
import type { ConversationMessage as Message, ConversationSummary } from '@atlas/backend-adapter';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import ConversationActivity from './ConversationActivity';
import ConversationMessage from './ConversationMessage';

const TERMINAL = ['completed', 'failed', 'cancelled'];

/**
 * A second conversation beside the current one, for reference or to keep an eye on a running
 * task. Read-only, except that its approvals and questions can be answered here.
 */
export default function SidePane({ conversation, username, onClose, onSwitch }: {
  conversation: ConversationSummary; username: string; onClose: () => void; onSwitch: () => void;
}) {
  const store = useAtlasStore();
  const [messages, setMessages] = useState<Message[] | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const run = [...store.runs].reverse().find((item) => item.conversationId === conversation.id);
  const live = run && !TERMINAL.includes(run.status) ? run : null;

  // Saved history; reloaded when this conversation's run finishes so its reply shows up.
  useEffect(() => {
    let stale = false;
    setMessages(null);
    backend.getMessages(conversation.id).then((result) => { if (!stale) setMessages(result.filter((item) => item.role === 'user' || item.role === 'assistant')); })
      .catch(() => { if (!stale) setMessages([]); });
    return () => { stale = true; };
  }, [conversation.id, run?.status]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }); }, [messages, live?.events.length]);

  const runPrompt = live ? String(live.events.find((event) => event.type === 'run.started')?.data.content ?? '') : '';
  const shown = messages && runPrompt ? messages.slice(0, Math.max(0, messages.map((item) => item.role === 'user' ? item.content : null).lastIndexOf(runPrompt))) : messages;

  return <section aria-label={`旁边的对话：${conversation.title}`} className="flex min-w-0 flex-1 flex-col shadow-[inset_1px_0_0_var(--line)]">
    <header className="flex h-10 shrink-0 items-center gap-2 pr-2 pl-5 shadow-[inset_0_-1px_0_var(--line)]">
      {live && <span aria-label="运行中" className="size-1.5 shrink-0 animate-pulse rounded-full bg-brand" />}
      <span className="min-w-0 flex-1 truncate text-[13px] text-fg-2" title={conversation.title}>{conversation.title}</span>
      <button onClick={onSwitch} title="切到这个对话" className="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg px-2 text-[12.5px] text-fg-3 hover:bg-hover hover:text-fg"><ArrowLeftRight size={13} />切过去</button>
      <button aria-label="关闭旁边的对话" onClick={onClose} className="grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={15} /></button>
    </header>
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto px-6 pt-1 pb-8">
      {shown === null ? <p className="py-6 text-center text-[13px] text-fg-3">正在载入…</p>
        : !shown.length && !live ? <p className="py-6 text-center text-[13px] text-fg-3">这个对话还是空的。</p>
        : shown.map((message) => <ConversationMessage key={message.id} role={message.role === 'user' ? 'user' : 'assistant'} content={message.content} username={username} />)}
      {live && <ConversationActivity events={live.events} store={store} username={username} setTab={() => onSwitch()} />}
    </div>
  </section>;
}
