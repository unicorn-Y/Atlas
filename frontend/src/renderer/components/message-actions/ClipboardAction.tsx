import { useEffect, useState } from 'react';
import { Check, ClipboardCopy } from 'lucide-react';

/** A real clipboard action shared by message and code-block toolbars. */
export default function ClipboardAction({ text, label = '复制消息' }: {
  text: string;
  label?: string;
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state === 'idle') return;
    const timer = window.setTimeout(() => setState('idle'), state === 'copied' ? 1200 : 2200);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch {
      setState('failed');
    }
  };

  const status = state === 'copied' ? '已复制' : state === 'failed' ? '复制失败' : label;
  return <button type="button" onClick={() => void copy()} title={status} aria-label={status}
    className="inline-flex size-7 items-center justify-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">
    {state === 'copied' ? <Check size={14} className="text-ok" /> : <ClipboardCopy size={14} />}
    <span className="sr-only" aria-live="polite">{status}</span>
  </button>;
}
