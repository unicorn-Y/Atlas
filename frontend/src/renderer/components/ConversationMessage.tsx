import { memo, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import Mark from './Mark';
import MermaidBlock from './MermaidBlock';

// ```mermaid blocks become diagrams; every other code block renders as usual.
const MARKDOWN_COMPONENTS = {
  code({ className, children, ...rest }: { className?: string; children?: ReactNode }) {
    if (className?.includes('language-mermaid')) return <MermaidBlock source={String(children ?? '').trimEnd()} />;
    return <code className={className} {...rest}>{children}</code>;
  },
};

const MARKDOWN_PLUGINS = { remarkPlugins: [remarkGfm], rehypePlugins: [rehypeHighlight], components: MARKDOWN_COMPONENTS };

/** 还在流式输出的回复：先按纯文本渲染（保留换行），message.completed 后再换完整 Markdown 渲染。 */
function StreamingText({ content }: { content: string }) {
  return <div className="prose-atlas whitespace-pre-wrap break-words">{content}</div>;
}

/**
 * One chat turn. The user speaks in the UI face inside a bubble; Atlas answers in serif, unboxed.
 * memo 化：历史消息在流式输出期间属性不变，不随每次 delta 重渲染。
 */
const ConversationMessage = memo(function ConversationMessage({ role, content, username, status, working = false, continued = false, note, actions, streaming = false }: {
  role: 'user' | 'assistant'; content: string; username: string; status?: string; working?: boolean;
  /** Small label above a user bubble, e.g. that it was folded into a running task. */
  note?: string;
  /** Controls revealed on hover, such as edit or fork. */
  actions?: ReactNode;
  /** Part of an Atlas turn that already showed its header; renders just the text, aligned under it. */
  continued?: boolean;
  /** 仍在生成中：用轻量纯文本渲染，落定后再切回完整 Markdown。 */
  streaming?: boolean;
}) {
  if (role === 'assistant' && continued) {
    return <div className="my-3 pl-10" data-message-role="assistant">
      <div className="prose-atlas">{streaming ? <StreamingText content={content} /> : <ReactMarkdown {...MARKDOWN_PLUGINS}>{content}</ReactMarkdown>}</div>
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
      {streaming ? <StreamingText content={content} /> : <div className="prose-atlas"><ReactMarkdown {...MARKDOWN_PLUGINS}>{content}</ReactMarkdown></div>}
      {actions && <div className="mt-1 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">{actions}</div>}
    </div>
  </div>;
});

export default ConversationMessage;
