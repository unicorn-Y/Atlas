import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { useAtlasStore } from '../store/useAtlasStore';

type Order = { id: string; name: string; owner_agent_id: string; enabled: boolean; instruction: string; scope: { kind: 'all' | 'workspace'; workspace?: string }; trigger: { keywords: string[] } };
type Audit = { triggered_at: string; conversation_workspace: string; matched_keywords: string[] };

export default function StandingOrdersPanel({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (message: string) => void }) {
  const agents = useAtlasStore((state) => state.agents).filter((agent) => agent.kind === 'persistent');
  const [items, setItems] = useState<Order[]>([]);
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<Order | null>(null);
  const [audit, setAudit] = useState<Record<string, Audit[]>>({});
  const refresh = () => void api<{ items: Order[] }>(apiBaseUrl, `/api/standing-orders?q=${encodeURIComponent(query)}`).then((result) => setItems(result.items)).catch((error) => onToast(error instanceof Error ? error.message : '读取常驻指令失败'));
  useEffect(refresh, [apiBaseUrl, query]);
  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!editing) return;
    try {
      const { id, ...payload } = editing;
      const saved = editing.id ? await api<Order>(apiBaseUrl, `/api/standing-orders/${id}`, { method: 'PATCH', json: payload }) : await api<Order>(apiBaseUrl, '/api/standing-orders', { method: 'POST', json: payload });
      setItems((current) => editing.id ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current]); setEditing(null); onToast('常驻指令已保存');
    } catch (error) { onToast(error instanceof Error ? error.message : '保存失败'); }
  };
  const remove = async (item: Order) => {
    if (!window.confirm(`删除常驻指令“${item.name}”？历史触发审计会保留。`)) return;
    try { await api(apiBaseUrl, `/api/standing-orders/${item.id}`, { method: 'DELETE' }); setItems((current) => current.filter((row) => row.id !== item.id)); onToast('常驻指令已删除'); }
    catch (error) { onToast(error instanceof Error ? error.message : '删除失败'); }
  };
  const toggle = async (item: Order) => {
    try { const saved = await api<Order>(apiBaseUrl, `/api/standing-orders/${item.id}`, { method: 'PATCH', json: { ...item, enabled: !item.enabled } }); setItems((current) => current.map((row) => row.id === saved.id ? saved : row)); }
    catch (error) { onToast(error instanceof Error ? error.message : '更新失败'); }
  };
  const showAudit = async (item: Order) => {
    try { const result = await api<{ items: Audit[] }>(apiBaseUrl, `/api/standing-orders/${item.id}/audit`); setAudit((current) => ({ ...current, [item.id]: result.items })); }
    catch (error) { onToast(error instanceof Error ? error.message : '读取审计失败'); }
  };
  return <section className="grid gap-3">
    <div className="flex flex-wrap items-center gap-2"><div className="min-w-0 flex-1"><h2 className="m-0 text-[16px] font-semibold">常驻指令</h2><p className="mb-0 mt-1 text-[12px] text-fg-3">默认 Atlas 和持久 Agent 都可使用；只在匹配的对话回合注入，不会按时间重复执行，也不触发心跳。</p></div><input aria-label="搜索常驻指令" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、内容、Agent…" className="rounded-lg border border-line bg-panel px-3 py-2 text-[12px] text-fg" /><button className="btn primary" disabled={!connected} onClick={() => setEditing({ id: '', name: '', owner_agent_id: 'atlas', enabled: true, instruction: '', scope: { kind: 'all' }, trigger: { keywords: [] } })}>新建常驻指令</button></div>
    {editing && <form onSubmit={(event) => void save(event)} className="card glass grid gap-3 p-4">
      <div className="grid gap-3 sm:grid-cols-2"><label className="grid gap-1 text-[12px] text-fg-2">名称<input required value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} className="rounded border border-line bg-panel p-2 text-fg" /></label>
        <label className="grid gap-1 text-[12px] text-fg-2">所属 Agent<select required value={editing.owner_agent_id} onChange={(event) => setEditing({ ...editing, owner_agent_id: event.target.value })} className="rounded border border-line bg-panel p-2 text-fg"><option value="atlas">默认 Atlas（普通对话）</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label></div>
      <label className="grid gap-1 text-[12px] text-fg-2">指令内容<textarea required maxLength={8000} rows={5} value={editing.instruction} onChange={(event) => setEditing({ ...editing, instruction: event.target.value })} className="rounded border border-line bg-panel p-2 text-fg" /></label>
      <div className="grid gap-3 sm:grid-cols-3"><label className="grid gap-1 text-[12px] text-fg-2">适用范围<select value={editing.scope.kind} onChange={(event) => setEditing({ ...editing, scope: { ...editing.scope, kind: event.target.value as 'all' | 'workspace' } })} className="rounded border border-line bg-panel p-2 text-fg"><option value="all">该 Agent 的所有工作区</option><option value="workspace">指定工作区</option></select></label>
        {editing.scope.kind === 'workspace' && <label className="grid gap-1 text-[12px] text-fg-2">工作区路径<input required value={editing.scope.workspace ?? ''} onChange={(event) => setEditing({ ...editing, scope: { ...editing.scope, workspace: event.target.value } })} className="rounded border border-line bg-panel p-2 text-fg" /></label>}
        <label className="grid gap-1 text-[12px] text-fg-2">触发关键词（逗号分隔，留空表示每个 turn）<input value={editing.trigger.keywords.join(', ')} onChange={(event) => setEditing({ ...editing, trigger: { keywords: event.target.value.split(',').map((word) => word.trim()).filter(Boolean).slice(0, 32) } })} className="rounded border border-line bg-panel p-2 text-fg" /></label></div>
      <label className="flex items-center gap-2 text-[12px] text-fg-2"><input type="checkbox" checked={editing.enabled} onChange={(event) => setEditing({ ...editing, enabled: event.target.checked })} />启用</label>
      <div className="flex justify-end gap-2"><button type="button" className="btn ghost" onClick={() => setEditing(null)}>取消</button><button className="btn primary" type="submit">保存</button></div>
    </form>}
    {items.map((item) => <article key={item.id} className="card glass grid gap-2 p-4"><div className="flex flex-wrap items-center gap-2"><b className="min-w-0 flex-1 text-[13px] text-fg">{item.name}</b><span className="text-[11px] text-fg-3">{item.owner_agent_id === 'atlas' ? '默认 Atlas（普通对话）' : agents.find((agent) => agent.id === item.owner_agent_id)?.name ?? item.owner_agent_id} · {item.enabled ? '启用' : '已暂停'}</span><button className="btn ghost" onClick={() => void toggle(item)}>{item.enabled ? '暂停' : '恢复'}</button><button className="btn ghost" onClick={() => setEditing(item)}>编辑</button><button className="btn ghost" onClick={() => void showAudit(item)}>最近触发</button><button className="btn ghost" onClick={() => void remove(item)}>删除</button></div><p className="m-0 whitespace-pre-wrap text-[12px] text-fg-2">{item.instruction}</p><p className="m-0 text-[10.5px] text-fg-3">{item.scope.kind === 'workspace' ? `工作区：${item.scope.workspace}` : '所有工作区'} · {item.trigger.keywords.length ? `关键词：${item.trigger.keywords.join('、')}` : '每个 turn 匹配'}</p>{audit[item.id] && <div className="border-t border-line pt-2 text-[11px] text-fg-3">{audit[item.id].length ? audit[item.id].map((entry, index) => <p key={`${entry.triggered_at}-${index}`} className="m-0">{new Date(entry.triggered_at).toLocaleString()} · {entry.conversation_workspace || '无工作区'}{entry.matched_keywords.length ? ` · 命中：${entry.matched_keywords.join('、')}` : ''}</p>) : <p className="m-0">暂无触发记录</p>}</div>}</article>)}
    {!items.length && <div className="card glass p-6 text-center text-[12px] text-fg-3">{query ? '没有匹配的常驻指令。' : '还没有常驻指令。'}</div>}
  </section>;
}
