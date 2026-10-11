/**
 * Adapted from anomalyco/opencode at 7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937 (MIT):
 * packages/app/src/session/timeline/search-controller.ts and search-bar.tsx.
 * Copyright (c) 2024-2026 OpenCode contributors.
 */
import { ChevronDown, ChevronUp, Search, X } from 'lucide-react';
import type { Ref } from 'react';

export interface ConversationSearchRow {
  id: string;
  text: string;
}

export interface ConversationSearchMatch {
  key: string;
  rowId: string;
  occurrence: number;
}

export function findConversationMatches(rows: ConversationSearchRow[], query: string): ConversationSearchMatch[] {
  const needle = query.trim();
  if (!needle) return [];
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(escaped, 'gi');
  const matches: ConversationSearchMatch[] = [];
  for (const row of rows) {
    pattern.lastIndex = 0;
    let occurrence = 0;
    while (pattern.exec(row.text)) {
      matches.push({ key: `${row.id}:${occurrence}`, rowId: row.id, occurrence });
      occurrence += 1;
    }
  }
  return matches;
}

function makeRanges(root: HTMLElement, query: string): Range[] {
  const needle = query.trim();
  if (!needle) return [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Array<{ node: Text; start: number; end: number }> = [];
  let text = '';
  let current: Node | null;
  while ((current = walker.nextNode())) {
    const node = current as Text;
    const value = node.nodeValue ?? '';
    nodes.push({ node, start: text.length, end: text.length + value.length });
    text += value;
  }

  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(escaped, 'gi');
  const ranges: Range[] = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    const start = match.index;
    const end = start + match[0].length;
    const first = nodes.find((entry) => entry.start <= start && entry.end > start);
    const last = [...nodes].reverse().find((entry) => entry.start < end && entry.end >= end);
    if (!first || !last) continue;
    const range = document.createRange();
    range.setStart(first.node, start - first.start);
    range.setEnd(last.node, end - last.start);
    ranges.push(range);
  }
  return ranges;
}

type HighlightRegistry = { set: (name: string, highlight: unknown) => void; delete: (name: string) => void };
type HighlightWindow = Window & {
  Highlight?: new (...ranges: Range[]) => unknown;
  CSS?: typeof CSS & { highlights?: HighlightRegistry };
};

export function clearConversationHighlights() {
  const registry = (window as HighlightWindow).CSS?.highlights;
  registry?.delete('atlas-conversation-search-hit');
  registry?.delete('atlas-conversation-search-active');
}

export function highlightConversationRow(root: HTMLElement, query: string, activeOccurrence: number): Range | null {
  clearConversationHighlights();
  const ranges = makeRanges(root, query);
  const active = ranges[activeOccurrence] ?? ranges[0] ?? null;
  const host = window as HighlightWindow;
  const HighlightCtor = host.Highlight;
  const registry = host.CSS?.highlights;
  if (HighlightCtor && registry && ranges.length) {
    registry.set('atlas-conversation-search-hit', new HighlightCtor(...ranges));
    if (active) registry.set('atlas-conversation-search-active', new HighlightCtor(active));
  }
  return active;
}

export function ConversationSearch({
  open,
  query,
  active,
  total,
  historyLoading,
  historyIncomplete,
  inputRef,
  onOpen,
  onQueryChange,
  onPrevious,
  onNext,
  onClose,
}: {
  open: boolean;
  query: string;
  active: number;
  total: number;
  historyLoading: boolean;
  historyIncomplete: boolean;
  inputRef: Ref<HTMLInputElement>;
  onOpen: () => void;
  onQueryChange: (query: string) => void;
  onPrevious: () => void;
  onNext: () => void;
  onClose: () => void;
}) {
  if (!open) return <div className="sticky top-2 z-30 h-0 overflow-visible pointer-events-none">
    <button type="button" onClick={onOpen} className="ml-auto flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[12px] text-fg-2 shadow pointer-events-auto hover:bg-surface-2" aria-label="在当前对话中查找">
      <Search size={14} />查找
    </button>
  </div>;
  return <>
    <style>{'::highlight(atlas-conversation-search-hit){background:rgba(250,204,21,.38);color:inherit}::highlight(atlas-conversation-search-active){background:rgba(249,115,22,.55);color:inherit;text-decoration:underline}'}</style>
    <div className="sticky top-2 z-30 h-0 overflow-visible pointer-events-none">
      <div className="ml-auto flex w-fit max-w-full items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1.5 shadow-lg pointer-events-auto" role="search" aria-label="在当前对话中查找">
        <Search size={14} className="shrink-0 text-fg-3" aria-hidden="true" />
        <input
          ref={inputRef}
          autoFocus
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="查找对话内容"
          aria-label="查找对话内容"
          className="w-48 bg-transparent text-[13px] text-fg outline-none placeholder:text-fg-3"
        />
        <span className="min-w-12 text-center text-[11px] tabular-nums text-fg-3" aria-live="polite">
          {historyLoading ? '载入中…' : historyIncomplete ? `${active ? active : 0} / ${total}+` : total ? `${active} / ${total}` : '0 / 0'}
        </span>
        <button type="button" onClick={onPrevious} disabled={!total} className="rounded p-1 text-fg-2 hover:bg-surface-2 disabled:opacity-40" aria-label="上一个匹配项"><ChevronUp size={14} /></button>
        <button type="button" onClick={onNext} disabled={!total} className="rounded p-1 text-fg-2 hover:bg-surface-2 disabled:opacity-40" aria-label="下一个匹配项"><ChevronDown size={14} /></button>
        <button type="button" onClick={onClose} className="rounded p-1 text-fg-2 hover:bg-surface-2" aria-label="关闭查找"><X size={14} /></button>
      </div>
    </div>
  </>;
}
