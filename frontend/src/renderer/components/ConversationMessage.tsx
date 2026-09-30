import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import Mark from './Mark';

/** One chat turn. The user speaks in the UI face inside a bubble; Atlas answers in serif, unboxed. */
export default function ConversationMessage({ role, content, username, status, working = false, continued = false, note, actions }: {
  role: 'user' | 'assistant'; content: string; username: string; status?: string; working?: boolean;
  /** Small label above a user bubble, e.g. that it was folded into a running task. */
  note?: string;
  /** Controls revealed on hover, such as edit or fork. */
  actions?: ReactNode;
  /** Part of an Atlas turn that already showed its header; renders just the text, aligned under it. */
  continued?: boolean;
}) {
  if (role === 'assistant' && continued) {
    return <div className="my-3 pl-10" data-message-role="assistant">
      <div className="prose-atlas"><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{content}</ReactMarkdown></div>
    </div>;
  }
  if (role === 'user') {
    return <div className="group my-5 flex flex-col items-end gap-1" data-message-role="user">
      {note && <span className="text-[11.5px] text-fg-3">{note}</span>}
      <div className="max-w-[78%] whitespace-pre-wrap rounded-[16px] rounded-br-[5px] bg-sunken px-4 py-2.5 text-[14.5px] leading-[1.7] text-fg shadow-[inset_0_0_0_1px_var(--line)]" title={username}>{content}</div>
      {actions && <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">{actions}</div>}
    </div>;
  }
  return <div className="group my-5 grid grid-cols-[28px_minmax(0,1fr)] gap-3" data-message-role="assistant">
    <Mark className="mt-[3px] size-[26px]" working={working} />
    <div className="min-w-0">
      <div className="mb-1.5 flex items-baseline gap-2.5">
        <b className="font-serif text-[14px] font-semibold tracking-[.04em] text-heading">Atlas</b>
        {status && <span className="text-[12px] text-fg-3">{status}</span>}
      </div>
      <div className="prose-atlas"><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{content}</ReactMarkdown></div>
      {actions && <div className="mt-1 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">{actions}</div>}
    </div>
  </div>;
}
