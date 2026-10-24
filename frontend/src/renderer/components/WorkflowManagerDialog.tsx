import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';

type Template = { id: string; name: string; goal: string };
type Node = { id: string; title?: string; goal: string; status: string; output?: string | null; error?: string | null; metadata?: Record<string, unknown> };
type Run = { workflow_id: string; status: string; created_at: string; updated_at: string; graph: { goal: string; nodes: Node[] }; events: Array<{ sequence?: number; timestamp?: string; type?: string; node_id?: string; message?: string; payload?: Record<string, unknown> }> };

export default function WorkflowManagerDialog({ apiBaseUrl, open, onClose, onRun, onToast }: {
  apiBaseUrl: string; open: boolean; onClose: () => void; onRun: (goal: string) => void; onToast: (text: string) => void;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState('');
  const [draftName, setDraftName] = useState('');
  const [draftGoal, setDraftGoal] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [saved, recent] = await Promise.all([
        api<{ templates: Template[] }>(apiBaseUrl, '/api/workflows/templates'),
        api<{ runs: Run[] }>(apiBaseUrl, '/api/workflows/runs?limit=100'),
      ]);
      setTemplates(saved.templates); setRuns(recent.runs); setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  }, [apiBaseUrl]);
  useEffect(() => { if (open) void refresh(); }, [open, refresh]);
  const currentRun = runs.find((run) => run.workflow_id === selected);
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api(apiBaseUrl, '/api/workflows/templates', { method: 'POST', json: { name: draftName, goal: draftGoal } });
      setDraftName(''); setDraftGoal(''); await refresh(); onToast('工作流模板已保存');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const edit = async (template: Template) => {
    const name = window.prompt('编辑模板名称', template.name); if (name === null) return;
    const goal = window.prompt('编辑工作流目标', template.goal); if (goal === null) return;
    try { await api(apiBaseUrl, `/api/workflows/templates/${encodeURIComponent(template.id)}`, { method: 'PUT', json: { name, goal } }); await refresh(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  const remove = async (template: Template) => {
    try { await api(apiBaseUrl, `/api/workflows/templates/${encodeURIComponent(template.id)}`, { method: 'DELETE' }); await refresh(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} label="动态工作流" className="flex max-h-[min(760px,calc(100vh-32px))] w-[min(980px,calc(100vw-32px))] flex-col bg-panel p-5">
    <header className="mb-4 flex items-center gap-3"><div className="min-w-0 flex-1"><h2 className="m-0 text-[17px] font-semibold text-heading">动态工作流</h2><p className="m-0 mt-1 text-[12.5px] text-fg-3">保存目标模板、重跑或改写参数；查看 DAG 节点、完整运行事件和产物。</p></div><Button variant="ghost" onClick={() => void refresh()}>刷新</Button></header>
    {error && <p role="alert" className="m-0 mb-3 rounded-lg bg-danger-soft p-2.5 text-[12px] text-danger">{error}</p>}
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(220px,0.8fr)_minmax(0,1.2fr)] gap-4 overflow-hidden">
      <div className="min-h-0 overflow-auto rounded-xl bg-sunken p-3">
        <h3 className="m-0 mb-2 text-[12px] font-semibold text-fg-2">保存的定义</h3>
        <div className="grid gap-1">{templates.map((template) => <div key={template.id} className="rounded-lg bg-panel p-2.5">
          <b className="block truncate text-[12.5px] text-fg">{template.name}</b><p className="m-0 mt-1 line-clamp-2 text-[11.5px] text-fg-3">{template.goal}</p>
          <div className="mt-2 flex gap-1.5"><button className="text-[11.5px] text-brand" onClick={() => { onRun(template.goal); onClose(); }}>运行</button><button className="text-[11.5px] text-fg-3" onClick={() => void edit(template)}>编辑</button><button className="text-[11.5px] text-danger" onClick={() => void remove(template)}>删除</button></div>
        </div>)}{!templates.length && <p className="text-[11.5px] text-fg-3">暂无模板。输入目标后保存，之后可修改或复跑。</p>}</div>
        <form onSubmit={(event) => void save(event)} className="mt-4 grid gap-2 border-t border-line pt-3">
          <h3 className="m-0 text-[12px] font-semibold text-fg-2">保存新定义</h3>
          <input aria-label="工作流模板名称" value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder="模板名称" required className="h-8 rounded-lg bg-panel px-2.5 text-[12px] text-fg" />
          <textarea aria-label="工作流模板目标" value={draftGoal} onChange={(event) => setDraftGoal(event.target.value)} placeholder="描述要拆分执行的目标" required rows={4} className="resize-y rounded-lg bg-panel p-2.5 text-[12px] text-fg" />
          <Button type="submit" disabled={busy}>{busy ? '保存中…' : '保存模板'}</Button>
        </form>
      </div>
      <div className="min-h-0 overflow-auto rounded-xl bg-sunken p-3">
        <h3 className="m-0 mb-2 text-[12px] font-semibold text-fg-2">最近运行</h3>
        <div className="mb-3 flex flex-wrap gap-1.5">{runs.map((run) => <button key={run.workflow_id} onClick={() => setSelected(run.workflow_id)} className={`rounded-lg px-2 py-1 text-[11.5px] ${selected === run.workflow_id ? 'bg-brand text-white' : 'bg-panel text-fg-2'}`}>{run.status} · {run.workflow_id.slice(0, 8)}</button>)}{!runs.length && <p className="text-[11.5px] text-fg-3">还没有已记录的运行。</p>}</div>
        {currentRun && <div className="grid gap-3">
          <section><b className="text-[12.5px] text-fg">{currentRun.graph.goal}</b><p className="m-0 mt-1 break-all font-mono text-[10.5px] text-fg-3">{currentRun.workflow_id} · {new Date(currentRun.updated_at).toLocaleString()}</p></section>
          <section><h4 className="m-0 mb-1.5 text-[11.5px] font-semibold text-fg-2">子任务与产出</h4><div className="grid gap-2">{currentRun.graph.nodes.map((node) => <article key={node.id} className="rounded-lg bg-panel p-2.5">
            <div className="flex gap-2"><b className="min-w-0 flex-1 text-[12px] text-fg">{node.title || node.goal}</b><span className="text-[11px] text-fg-3">{node.status}</span></div>
            {node.error && <pre className="my-1 whitespace-pre-wrap text-[11px] text-danger">{node.error}</pre>}{node.output && <pre className="my-1 max-h-28 overflow-auto whitespace-pre-wrap text-[11px] text-fg-2">{node.output}</pre>}
            {Array.isArray(node.metadata?.artifacts) && (node.metadata!.artifacts as Array<{ path?: string; name?: string }>).map((artifact, i) => <p key={i} className="m-0 text-[11px] text-brand">产物：{artifact.name || artifact.path}</p>)}
          </article>)}</div></section>
          <section><h4 className="m-0 mb-1.5 text-[11.5px] font-semibold text-fg-2">事件日志（{currentRun.events.length}）</h4><ol className="m-0 grid list-none gap-1 p-0">{currentRun.events.map((event, i) => <li key={`${event.sequence}-${i}`} className="break-words text-[10.5px] text-fg-3">{event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''} · {event.type} {event.node_id ?? ''} {event.message ?? ''}</li>)}</ol></section>
        </div>}
      </div>
    </div>
  </Dialog>;
}
