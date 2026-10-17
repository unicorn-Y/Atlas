import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';

type Props = { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void };
type Stats = { root: string; raw: Record<string, number>; curated: Record<string, number>; evals: string[] };
type Hit = { path: string; kind: string; title: string; snippet: string; source: string };

const KINDS = ['事实', '技能', '决策', '案例'];

export default function KnowledgePanel({ apiBaseUrl, connected, onToast }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ kind: '技能', title: '', body: '' });

  const refresh = useCallback(() => {
    void api<Stats>(apiBaseUrl, '/api/knowledge/stats').then(setStats).catch((e: unknown) => onToast(`知识库：${e instanceof Error ? e.message : String(e)}`));
  }, [apiBaseUrl, onToast]);
  useEffect(() => { if (connected) refresh(); }, [connected, refresh]);

  const search = async () => {
    if (!query.trim()) return;
    const result = await api<{ results: Hit[] }>(apiBaseUrl, `/api/knowledge/search?q=${encodeURIComponent(query)}`);
    setHits(result.results);
  };
  const importFrom = async (source: string) => {
    setBusy(true);
    try {
      const r = await api<{ copied: number; skipped: number; errors: string[] }>(apiBaseUrl, '/api/knowledge/import', { method: 'POST', json: { source } });
      onToast(`导入 ${source}：新增 ${r.copied}，跳过 ${r.skipped}${r.errors.length ? `，出错 ${r.errors.length}` : ''}`);
      refresh();
    } catch (e) { onToast(String(e)); } finally { setBusy(false); }
  };
  const add = async () => {
    if (!draft.title.trim() || !draft.body.trim()) return;
    try {
      await api(apiBaseUrl, '/api/knowledge/item', { method: 'POST', json: draft });
      onToast('已加入知识库'); setDraft({ ...draft, title: '', body: '' }); refresh();
    } catch (e) { onToast(String(e)); }
  };

  return (
    <section style={{ marginTop: 24, padding: 16, border: '1px solid var(--border, #8884)', borderRadius: 8 }}>
      <h3 style={{ margin: '0 0 8px' }}>知识库</h3>
      <div style={{ fontSize: 13, opacity: 0.8 }}>
        提炼层：{KINDS.map((k) => `${k} ${stats?.curated[k] ?? 0}`).join(' · ')}
        {' ｜ '}原始档案：{stats && Object.keys(stats.raw).length ? Object.entries(stats.raw).map(([k, v]) => `${k} ${v}`).join(' · ') : '无'}
        {' ｜ '}评测集：{stats?.evals.length ?? 0}
      </div>
      <div style={{ display: 'flex', gap: 8, margin: '12px 0' }}>
        <button disabled={busy} onClick={() => void importFrom('claude-code')}>导入 Claude Code 会话</button>
        <button disabled={busy} onClick={() => void importFrom('codex')}>导入 Codex 会话</button>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input style={{ flex: 1 }} value={query} placeholder="搜索知识库" onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void search(); }} />
        <button onClick={() => void search()}>搜索</button>
      </div>
      {hits.map((h) => (
        <div key={h.path} style={{ padding: '8px 0', borderBottom: '1px solid var(--border, #8882)' }}>
          <b>[{h.kind}] {h.title}</b>
          <div style={{ fontSize: 13, opacity: 0.8, whiteSpace: 'pre-wrap' }}>{h.snippet}</div>
        </div>
      ))}
      <div style={{ display: 'grid', gap: 6, marginTop: 12 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
            {KINDS.map((k) => <option key={k}>{k}</option>)}
          </select>
          <input style={{ flex: 1 }} value={draft.title} placeholder="标题" onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        </div>
        <textarea rows={3} value={draft.body} placeholder="内容" onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
        <button onClick={() => void add()}>手动加一条</button>
      </div>
    </section>
  );
}
