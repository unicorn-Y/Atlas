/*
 * Atlas wrapper around the ZCode reasoning block (components/reasoning/*, ported from
 * zai-org/ZCode packages/ui/src/components/ai-elements/reasoning.tsx and its helpers).
 * Open by default and left open (like Hermes): the reader follows the model's thinking as it streams
 * and can still read it afterwards; collapsing is the reader's choice. Collapsed, the trigger shows
 * "正在思考 · <newest line>". Atlas extras kept: copy button and the truncation note.
 */
import { useState } from 'react';
import { ClipboardCopy } from 'lucide-react';
import { Reasoning, ReasoningContent, ReasoningTrigger } from './reasoning/Reasoning';

function spanSeconds(startedAt?: string, endedAt?: string): number | undefined {
  if (!startedAt || !endedAt) return undefined;
  const span = Date.parse(endedAt) - Date.parse(startedAt);
  return Number.isFinite(span) && span >= 0 ? Math.max(1, Math.ceil(span / 1000)) : undefined;
}

export default function ReasoningBlock({ text, streaming, startedAt, endedAt, truncated, durationMs }: {
  text: string;
  streaming: boolean;
  startedAt?: string;
  endedAt?: string;
  truncated?: boolean;
  /** Real thinking span when the backend recorded one (history rows). */
  durationMs?: number;
}) {
  const [copied, setCopied] = useState(false);
  // An empty streaming thought has nothing to show yet (ZCode ReasoningRowView).
  if (streaming && !text.trim()) return null;
  const duration = streaming ? undefined
    : durationMs !== undefined ? Math.max(1, Math.ceil(durationMs / 1000)) : spanSeconds(startedAt, endedAt);

  const footer = !streaming && <button type="button" onClick={() => {
    void navigator.clipboard?.writeText(text).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); }).catch(() => undefined);
  }} className="ml-[22px] mt-1 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-fg-3 hover:bg-hover hover:text-fg">
    <ClipboardCopy size={12} aria-hidden="true" />{copied ? '已复制' : '复制思考'}
  </button>;

  return <div className="my-2 min-w-0" data-conversation-selectable="true">
    <Reasoning className="w-full" isStreaming={streaming} defaultOpen
      {...(duration !== undefined ? { duration } : {})}>
      <ReasoningTrigger streamingText={text} />
      <ReasoningContent footer={footer}>
        {text.trim() + (truncated ? '\n\n（思考内容过长，只保留了前 60,000 字）' : '')}
      </ReasoningContent>
    </Reasoning>
  </div>;
}
