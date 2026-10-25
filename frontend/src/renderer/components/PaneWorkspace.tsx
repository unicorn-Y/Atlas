import { useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { ArrowDown, X } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import type { DragEvent as ReactDragEvent, ReactNode } from 'react';
import SidePane from './SidePane';

type Leaf = { kind: 'pane'; id: string };
type Split = { kind: 'split'; splitId: string; axis: 'row' | 'column'; ratio: number; first: PaneNode; second: PaneNode };
type PaneNode = Leaf | Split;
const STORAGE = 'atlas.preference.pane-layout';
const isLeaf = (node: PaneNode): node is Leaf => node.kind === 'pane';
function ids(node: PaneNode | null): string[] { return !node ? [] : isLeaf(node) ? [node.id] : [...ids(node.first), ...ids(node.second)]; }
function remove(node: PaneNode | null, id: string): PaneNode | null {
  if (!node) return null;
  if (isLeaf(node)) return node.id === id ? null : node;
  const first = remove(node.first, id), second = remove(node.second, id);
  if (!first) return second; if (!second) return first;
  return { ...node, first, second };
}
function splitAt(node: PaneNode, target: string, id: string, axis: Split['axis'], before: boolean): PaneNode {
  if (isLeaf(node)) return node.id === target
    ? { kind: 'split', splitId: crypto.randomUUID(), axis, ratio: 0.5, first: before ? { kind: 'pane', id } : node, second: before ? node : { kind: 'pane', id } }
    : node;
  return { ...node, first: splitAt(node.first, target, id, axis, before), second: splitAt(node.second, target, id, axis, before) };
}

/** Recursive session pane tree. Ratios and pane membership persist in the local UI preference. */
export default function PaneWorkspace({ besideId, activeId, conversations, username, onSwitch }: {
  besideId: string; activeId: string; conversations: ConversationSummary[]; username: string; onSwitch: (conversation: ConversationSummary) => void;
}) {
  const [layout, setLayout] = useState<PaneNode | null>(() => {
    try { const raw = localStorage.getItem(STORAGE); return raw ? JSON.parse(raw) as PaneNode : besideId ? { kind: 'pane', id: besideId } : null; }
    catch { return besideId ? { kind: 'pane', id: besideId } : null; }
  });
  const [focused, setFocused] = useState(besideId);
  const [dragged, setDragged] = useState('');
  const byId = useMemo(() => new Map(conversations.map((item) => [item.id, item])), [conversations]);
  const panes = ids(layout).filter((id) => id !== activeId && byId.has(id));
  useEffect(() => { window.dispatchEvent(new CustomEvent('atlas:panes-change', { detail: { count: panes.length } })); }, [panes.join('|')]);
  useEffect(() => {
    if (besideId && besideId !== activeId && !ids(layout).includes(besideId)) {
      setLayout((current) => current ? { kind: 'split', splitId: crypto.randomUUID(), axis: 'row', ratio: 0.5, first: current, second: { kind: 'pane', id: besideId } } : { kind: 'pane', id: besideId });
      setFocused(besideId);
    }
  }, [besideId, activeId]);
  useEffect(() => {
    if (activeId && ids(layout).includes(activeId)) setLayout((current) => remove(current, activeId));
  }, [activeId]);
  useEffect(() => { try { if (layout) localStorage.setItem(STORAGE, JSON.stringify(layout)); else localStorage.removeItem(STORAGE); } catch { /* preference storage is optional */ } }, [layout]);
  useEffect(() => {
    const focus = (event: Event) => {
      const step = Number((event as CustomEvent<{ step?: number }>).detail?.step ?? 1);
      const current = [activeId, ...ids(layout).filter((id) => id !== activeId && byId.has(id))].filter(Boolean);
      if (current.length) {
        const next = current[(Math.max(0, current.indexOf(focused)) + step + current.length) % current.length];
        if (next === activeId) { setFocused(activeId); document.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息内容"]')?.focus(); window.dispatchEvent(new Event('atlas:focus-main-pane')); }
        else { setFocused(next); document.querySelector<HTMLElement>(`[data-pane-id="${CSS.escape(next)}"]`)?.focus(); window.dispatchEvent(new Event('atlas:focus-side-pane')); }
      }
    };
    window.addEventListener('atlas:focus-pane', focus);
    return () => window.removeEventListener('atlas:focus-pane', focus);
  }, [layout, focused, activeId, byId]);

  const resize = (event: ReactPointerEvent<HTMLDivElement>, node: Split) => {
    event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId);
    const host = event.currentTarget.parentElement;
    if (!host) return;
    const rect = host.getBoundingClientRect();
    const update = (pointer: PointerEvent) => {
      const ratio = node.axis === 'row' ? (pointer.clientX - rect.left) / rect.width : (pointer.clientY - rect.top) / rect.height;
      const value = Math.max(0.18, Math.min(0.82, ratio));
      setLayout((current) => current ? updateRatio(current, node, value) : current);
    };
    const stop = () => { window.removeEventListener('pointermove', update); window.removeEventListener('pointerup', stop); };
    window.addEventListener('pointermove', update); window.addEventListener('pointerup', stop, { once: true });
  };
  const addAt = (target: string, id: string, axis: Split['axis'], before = false) => {
    if (!layout || id === activeId || id === target) return;
    const without = remove(layout, id);
    if (!without) { setLayout({ kind: 'pane', id }); return; }
    setLayout(splitAt(without, target, id, axis, before)); setFocused(id);
  };
  const addToMain = (id: string, axis: Split['axis'], before: boolean) => {
    if (!byId.has(id) || id === activeId) return;
    setLayout((current) => {
      const without = remove(current, id);
      if (!without) return { kind: 'pane', id };
      const target = ids(without).find((candidate) => candidate !== activeId);
      return target ? splitAt(without, target, id, axis, before) : { kind: 'pane', id };
    });
    setFocused(id);
  };
  useEffect(() => {
    const drop = (event: Event) => {
      const detail = (event as CustomEvent<{ id: string; axis: Split['axis']; before: boolean }>).detail;
      if (detail) addToMain(detail.id, detail.axis, detail.before);
    };
    window.addEventListener('atlas:drop-pane', drop);
    return () => window.removeEventListener('atlas:drop-pane', drop);
  }, [activeId, byId]);
  const acceptDrop = (event: ReactDragEvent, target: string) => {
    event.preventDefault();
    const sessionId = event.dataTransfer.getData('text/plain') || dragged;
    if (!byId.has(sessionId)) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width, y = (event.clientY - rect.top) / rect.height;
    const axis: Split['axis'] = Math.min(x, 1 - x) < Math.min(y, 1 - y) ? 'row' : 'column';
    const before = axis === 'row' ? x < 0.5 : y < 0.5;
    addAt(target, sessionId, axis, before); setDragged('');
  };
  const render = (node: PaneNode): ReactNode => {
    if (isLeaf(node)) {
      const conversation = byId.get(node.id);
      if (!conversation || node.id === activeId) return null;
      return <section key={node.id} tabIndex={0} data-pane-id={node.id} onClick={() => { setFocused(node.id); window.dispatchEvent(new Event('atlas:focus-side-pane')); }} onDragOver={(event) => event.preventDefault()} onDrop={(event) => acceptDrop(event, node.id)}
        className={`relative flex min-h-0 min-w-0 flex-1 flex-col ${focused === node.id ? 'ring-1 ring-inset ring-brand/60' : ''}`}
        onDragStart={(event) => { setDragged(node.id); event.dataTransfer.setData('text/plain', node.id); event.dataTransfer.effectAllowed = 'move'; }} draggable>
        <div className="no-drag flex h-7 shrink-0 items-center justify-end gap-1 border-b border-line px-1.5">
          <select aria-label="添加分屏会话" value="" onChange={(event) => { if (event.target.value) addAt(node.id, event.target.value, 'row'); }} className="max-w-32 rounded bg-sunken px-1 py-0.5 text-[10px] text-fg-2">
            <option value="">＋右侧会话</option>{conversations.filter((item) => item.id !== activeId && !panes.includes(item.id)).map((item) => <option key={item.id} value={item.id}>{item.title || '未命名'}</option>)}
          </select>
          <button type="button" title="新增下方分屏" onClick={() => { const id = conversations.find((item) => item.id !== activeId && !panes.includes(item.id))?.id; if (id) addAt(node.id, id, 'column'); }} className="rounded p-1 text-fg-3 hover:bg-hover"><ArrowDown size={12} /></button>
          <button type="button" aria-label="关闭分屏" onClick={() => { setLayout((current) => remove(current, node.id)); if (focused === node.id) setFocused(activeId); }} className="rounded p-1 text-fg-3 hover:bg-hover"><X size={12} /></button>
        </div>
        <div className="min-h-0 flex-1"><SidePane conversation={conversation} username={username} onClose={() => setLayout((current) => remove(current, node.id))} onSwitch={() => onSwitch(conversation)} /></div>
      </section>;
    }
    return <div key={node.splitId} className={`flex min-h-0 min-w-0 flex-1 ${node.axis === 'row' ? 'flex-row' : 'flex-col'}`}>
      <div className="flex min-h-0 min-w-0" style={{ flex: `${node.ratio} 1 0%` }}>{render(node.first)}</div>
      <div role="separator" aria-orientation={node.axis === 'row' ? 'vertical' : 'horizontal'} aria-label="调整分屏比例" onPointerDown={(event) => resize(event, node)} className={`${node.axis === 'row' ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize'} shrink-0 bg-line hover:bg-brand`} />
      <div className="flex min-h-0 min-w-0" style={{ flex: `${1 - node.ratio} 1 0%` }}>{render(node.second)}</div>
    </div>;
  };
  if (!layout || !panes.length) return null;
  return <div className="flex min-h-0 min-w-0 flex-1" aria-label="多会话分屏"><div className="sr-only">焦点分屏：{byId.get(focused)?.title || '当前对话'}。拖动会话标题可重新排列，分隔条可调整大小。</div>{render(layout)}</div>;
}

function updateRatio(root: PaneNode, target: Split, ratio: number): PaneNode {
  if (!isLeaf(root) && root.splitId === target.splitId) return { ...root, ratio };
  if (isLeaf(root)) return root;
  return { ...root, first: updateRatio(root.first, target, ratio), second: updateRatio(root.second, target, ratio) };
}
