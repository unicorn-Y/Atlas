import { useEffect, useMemo, useState } from 'react';
import type { ConversationSummary, ConversationMessage } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { api } from '../services/api';
import { Dialog } from '../ui/Dialog';
import { FormattedMessageContent } from './ConversationMessage';

type SearchHit = { conversation_id: string };
export default function ResumePickerDialog({ apiBaseUrl, conversations, onClose, onSelect }: {
  apiBaseUrl: string; conversations: ConversationSummary[]; onClose: () => void;
  onSelect: (conversation: ConversationSummary) => void;
}) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(conversations[0]?.id ?? '');
  const [contentMatches, setContentMatches] = useState<string[]>([]);
  const [preview, setPreview] = useState<ConversationMessage[]>([]);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const q = query.trim().toLocaleLowerCase();
  useEffect(() => {
    if (!q) { setContentMatches([]); return; }
    let stale = false;
    const timer = window.setTimeout(() => void api<SearchHit[]>(apiBaseUrl, `/api/search?limit=100&q=${encodeURIComponent(query.trim())}`)
      .then((hits) => { if (!stale) setContentMatches([...new Set(hits.map((hit) => hit.conversation_id))]); })
      .catch(() => { if (!stale) setContentMatches([]); }), 180);
    return () => { stale = true; window.clearTimeout(timer); };
  }, [apiBaseUrl, query, q]);
  const rows = useMemo(() => conversations.filter((item) => !q || item.title.toLocaleLowerCase().includes(q) || item.id.toLocaleLowerCase().includes(q) || contentMatches.includes(item.id)), [conversations, q, contentMatches]);
  useEffect(() => { if (!rows.some((row) => row.id === selected)) setSelected(rows[0]?.id ?? ''); }, [rows, selected]);
  useEffect(() => {
    if (!selected) { setPreview([]); return; }
    let stale = false;
    setPreview([]);
    setLoadingPreview(true);
    setPreviewError('');
    void backend.getMessages(selected, { limit: 8 }).then((messages) => { if (!stale) setPreview(messages); })
      .catch((error) => { if (!stale) { setPreview([]); setPreviewError(error instanceof Error ? error.message : String(error)); } })
      .finally(() => { if (!stale) setLoadingPreview(false); });
    return () => { stale = true; };
  }, [selected]);
  const open = () => { const target = conversations.find((item) => item.id === selected); if (target) { onClose(); onSelect(target); } };
  return <Dialog open onOpenChange={(value) => { if (!value) onClose(); }} label="选择要恢复的对话" className="w-[min(850px,calc(100vw-32px))]">
    <div className="border-b border-line px-4 py-3"><h2 className="m-0 text-[15px] font-semibold text-fg">恢复对话</h2><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或正文…" aria-label="搜索对话标题或正文" className="mt-2 h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-fg outline-none focus:border-brand" /></div>
    <div className="grid h-[min(55vh,480px)] min-h-[280px] grid-cols-[minmax(210px,0.8fr)_minmax(0,1.2fr)]">
      <div className="overflow-auto border-r border-line p-1.5" role="listbox" aria-label="对话列表">{rows.map((row) => <button key={row.id} role="option" aria-selected={selected === row.id} onClick={() => setSelected(row.id)} onDoubleClick={open} className={`block w-full rounded-lg px-3 py-2 text-left ${selected === row.id ? 'bg-selected' : 'hover:bg-hover'}`}><span className="block truncate text-[13px] text-fg">{row.title || '新对话'}</span><span className="block truncate text-[11px] text-fg-3">{row.workspace ?? row.id}</span></button>)}{!rows.length && <p className="px-3 text-[12px] text-fg-3">没有匹配的对话</p>}</div>
      <div className="overflow-auto p-4" aria-label="对话预览" aria-busy={loadingPreview}>
        {loadingPreview && <p role="status" className="m-0 mb-3 text-[12px] text-fg-3">正在加载最近消息…</p>}
        {previewError && <p role="alert" className="m-0 mb-3 text-[12px] text-danger">预览读取失败：{previewError}</p>}
        {preview.map((message) => <article key={message.id} className="mb-3 rounded-lg border border-line bg-sunken p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-fg-3"><b className="font-medium text-fg-2">{message.role === 'user' ? '你' : message.role === 'assistant' ? 'Atlas' : message.role}</b><time dateTime={message.created_at}>{message.created_at ? new Date(message.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '时间未知'}</time></div>
          <FormattedMessageContent content={message.content} />
        </article>)}
        {selected && !loadingPreview && !previewError && !preview.length && <p className="text-[12px] text-fg-3">这段对话还没有可预览的消息</p>}
      </div>
    </div>
    <div className="flex items-center justify-end gap-2 border-t border-line p-3"><button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-[12px] text-fg-2 hover:bg-hover">取消</button><button type="button" disabled={!selected} onClick={open} className="rounded-lg bg-brand px-4 py-2 text-[12px] text-white disabled:opacity-40">打开对话</button></div>
    <PickerEnter onOpen={open} />
  </Dialog>;
}

function PickerEnter({ onOpen }: { onOpen: () => void }) {
  useEffect(() => { const handler = (event: KeyboardEvent) => { if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement)) { event.preventDefault(); onOpen(); } }; window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }, [onOpen]);
  return null;
}
