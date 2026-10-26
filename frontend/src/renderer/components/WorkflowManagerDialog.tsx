import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';

type Step = { id: string; title: string; goal: string; depends_on: string[]; acceptance: string[] };
type Template = { id: string; name: string; goal: string; steps: Step[]; builtin?: boolean };
type Node = { id: string; title?: string; goal: string; status: string; output?: string | null; error?: string | null; metadata?: Record<string, unknown> };
type Run = { workflow_id: string; status: string; created_at: string; updated_at: string; graph: { goal: string; nodes: Node[] }; events: Array<{ sequence?: number; timestamp?: string; type?: string; node_id?: string; message?: string; payload?: Record<string, unknown> }> };

const emptyBlueprint = (): Template => ({ id: '', name: '', goal: '', steps: [{ id: 'step-1', title: '', goal: '', depends_on: [], acceptance: [''] }] });
const clone = (template: Template): Template => structuredClone(template);

export default function WorkflowManagerDialog({ apiBaseUrl, open, onClose, onRun, onToast }: {
  apiBaseUrl: string; open: boolean; onClose: () => void; onRun: (goal: string) => void; onToast: (text: string) => void;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState('');
  const [draft, setDraft] = useState<Template>(emptyBlueprint);
  const [selectedRun, setSelectedRun] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [saved, recent] = await Promise.all([
        api<{ templates: Template[] }>(apiBaseUrl, '/api/workflows/templates'),
        api<{ runs: Run[] }>(apiBaseUrl, '/api/workflows/runs?limit=100'),
      ]);
      setTemplates(saved.templates); setRuns(recent.runs); setError('');
      const current = saved.templates.find((item) => item.id === selected) ?? saved.templates[0];
      if (current) { setSelected(current.id); setDraft(clone(current)); }
      if (!selected && !current) { setSelected(''); setDraft(emptyBlueprint()); }
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  }, [apiBaseUrl, selected]);
  useEffect(() => { if (open) void refresh(); }, [open, apiBaseUrl]);
  const currentRun = runs.find((run) => run.workflow_id === selectedRun);
  const selectTemplate = (template: Template) => { setSelected(template.id); setDraft(clone(template)); };
  const updateStep = (index: number, patch: Partial<Step>) => setDraft((current) => ({ ...current, steps: current.steps.map((step, at) => at === index ? { ...step, ...patch } : step) }));
  const moveStep = (index: number, delta: number) => setDraft((current) => {
    const next = [...current.steps]; const target = index + delta;
    if (target < 0 || target >= next.length) return current;
    [next[index], next[target]] = [next[target], next[index]];
    return { ...current, steps: next };
  });
  const save = async () => {
    setBusy(true); setError('');
    const payload = { name: draft.name, goal: draft.goal, steps: draft.steps.map((step) => ({ ...step,
      depends_on: step.depends_on.filter(Boolean), acceptance: step.acceptance.map((item) => item.trim()).filter(Boolean) })) };
    try {
      const result = draft.id && !draft.id.startsWith('builtin-')
        ? await api<{ template: Template }>(apiBaseUrl, `/api/workflows/templates/${encodeURIComponent(draft.id)}`, { method: 'PUT', json: payload })
        : await api<{ template: Template }>(apiBaseUrl, '/api/workflows/templates', { method: 'POST', json: payload });
      await refresh(); selectTemplate(result.template); onToast('Blueprint 已保存');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!draft.id || draft.id.startsWith('builtin-')) return;
    try { await api(apiBaseUrl, `/api/workflows/templates/${encodeURIComponent(draft.id)}`, { method: 'DELETE' }); setSelected(''); setDraft(emptyBlueprint()); await refresh(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  const run = () => {
    const plan = draft.steps.map((step, index) => ({ order: index + 1, id: step.id, title: step.title, goal: step.goal, depends_on: step.depends_on, acceptance: step.acceptance }));
    onRun(`按以下 Blueprint 创建可编辑的有序工作流 DAG。执行前保留步骤顺序、依赖和验收项；如果拆解需要调整，先在计划中提出编辑结果再执行。\n\n目标：${draft.goal}\n模板：${draft.name}\n步骤计划（JSON）：\n${JSON.stringify(plan, null, 2)}`);
    onClose();
  };
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} label="动态工作流" className="flex max-h-[min(820px,calc(100vh-32px))] w-[min(1100px,calc(100vw-32px))] flex-col bg-panel p-5">
    <header className="mb-4 flex items-center gap-3"><div className="min-w-0 flex-1"><h2 className="m-0 text-[17px] font-semibold text-heading">Blueprint 工作流</h2><p className="m-0 mt-1 text-[12.5px] text-fg-3">选择内置蓝图或保存自己的步骤方案；顺序、依赖与验收项在运行前可编辑。</p></div><Button variant="ghost" onClick={() => { setSelected(''); setDraft(emptyBlueprint()); }}>新建 Blueprint</Button><Button variant="ghost" onClick={() => void refresh()}>刷新</Button></header>
    {error && <p role="alert" className="m-0 mb-3 rounded-lg bg-danger-soft p-2.5 text-[12px] text-danger">{error}</p>}
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(180px,0.65fr)_minmax(0,1.5fr)] gap-4 overflow-hidden">
      <div className="min-h-0 overflow-auto rounded-xl bg-sunken p-3">
        <h3 className="m-0 mb-2 text-[12px] font-semibold text-fg-2">蓝图模板</h3>
        <div className="grid gap-1">{templates.map((template) => <button key={template.id} onClick={() => selectTemplate(template)} className={`rounded-lg p-2.5 text-left ${selected === template.id ? 'bg-selected' : 'bg-panel hover:bg-hover'}`}>
          <b className="block truncate text-[12.5px] text-fg">{template.name}</b><span className="mt-1 block text-[10.5px] text-fg-3">{template.builtin ? '内置' : '我的模板'} · {template.steps?.length ?? 1} 步</span>
        </button>)}</div>
        <h3 className="mt-5 mb-2 text-[12px] font-semibold text-fg-2">最近运行</h3>
        <div className="grid gap-1">{runs.map((item) => <button key={item.workflow_id} onClick={() => setSelectedRun(item.workflow_id)} className={`rounded-md px-2 py-1 text-left text-[11px] ${selectedRun === item.workflow_id ? 'bg-brand text-white' : 'bg-panel text-fg-2'}`}>{item.status} · {item.workflow_id.slice(0, 8)}</button>)}{!runs.length && <p className="text-[11px] text-fg-3">还没有已记录的运行。</p>}</div>
      </div>
      <div className="min-h-0 overflow-auto rounded-xl bg-sunken p-3">
        <div className="grid gap-2"><label className="grid gap-1 text-[11px] text-fg-3">模板名称<input aria-label="Blueprint 名称" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className="h-8 rounded-lg bg-panel px-2.5 text-[12px] text-fg" /></label>
          <label className="grid gap-1 text-[11px] text-fg-3">工作流目标<textarea aria-label="Blueprint 目标" value={draft.goal} onChange={(event) => setDraft({ ...draft, goal: event.target.value })} rows={2} className="resize-y rounded-lg bg-panel p-2.5 text-[12px] text-fg" /></label></div>
        <div className="mt-3 grid gap-2">{draft.steps.map((step, index) => <article key={`${step.id}-${index}`} className="rounded-lg bg-panel p-3">
          <header className="mb-2 flex items-center gap-2"><b className="flex-1 text-[12px] text-fg">第 {index + 1} 步 · {step.id}</b><button type="button" aria-label="步骤上移" disabled={index === 0} onClick={() => moveStep(index, -1)} className="text-[11px] text-brand disabled:opacity-30">上移</button><button type="button" aria-label="步骤下移" disabled={index === draft.steps.length - 1} onClick={() => moveStep(index, 1)} className="text-[11px] text-brand disabled:opacity-30">下移</button><button type="button" aria-label="删除步骤" disabled={draft.steps.length <= 1} onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, at) => at !== index) })} className="text-[11px] text-danger disabled:opacity-30">删除</button></header>
          <div className="grid gap-2"><input aria-label={`步骤 ${index + 1} 标题`} value={step.title} onChange={(event) => updateStep(index, { title: event.target.value })} placeholder="步骤标题" className="h-8 rounded-lg bg-sunken px-2.5 text-[12px] text-fg" />
            <textarea aria-label={`步骤 ${index + 1} 目标`} value={step.goal} onChange={(event) => updateStep(index, { goal: event.target.value })} placeholder="这一步要完成什么" rows={2} className="resize-y rounded-lg bg-sunken p-2.5 text-[12px] text-fg" />
            <label className="grid gap-1 text-[10.5px] text-fg-3">依赖步骤（ID，以逗号分隔）<input aria-label={`步骤 ${index + 1} 依赖`} value={step.depends_on.join(', ')} onChange={(event) => updateStep(index, { depends_on: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} placeholder="例如：inspect" className="h-7 rounded-md bg-sunken px-2 text-[11px] text-fg" /></label>
            <label className="grid gap-1 text-[10.5px] text-fg-3">验收项（每行一项）<textarea aria-label={`步骤 ${index + 1} 验收项`} value={step.acceptance.join('\n')} onChange={(event) => updateStep(index, { acceptance: event.target.value.split('\n') })} rows={2} className="resize-y rounded-lg bg-sunken p-2 text-[11px] text-fg" /></label></div>
        </article>)}
          <Button variant="ghost" onClick={() => { let suffix = draft.steps.length + 1; while (draft.steps.some((step) => step.id === `step-${suffix}`)) suffix += 1; const id = `step-${suffix}`; setDraft({ ...draft, steps: [...draft.steps, { id, title: '', goal: '', depends_on: draft.steps.length ? [draft.steps[draft.steps.length - 1].id] : [], acceptance: [''] }] }); }}>添加步骤</Button>
        </div>
        <div className="sticky bottom-0 mt-3 flex flex-wrap justify-end gap-2 border-t border-line bg-sunken py-3"><Button variant="ghost" disabled={!draft.id || draft.id.startsWith('builtin-')} onClick={() => void remove()}>删除模板</Button><Button variant="ghost" disabled={busy || !draft.name || !draft.goal} onClick={() => void save()}>{busy ? '保存中…' : draft.id?.startsWith('builtin-') ? '另存为我的模板' : '保存模板变更'}</Button><Button variant="primary" disabled={!draft.name || !draft.goal || draft.steps.some((step) => !step.title || !step.goal || !step.acceptance.some((item) => item.trim()))} onClick={run}>按此方案创建工作流</Button></div>
        {currentRun && <section className="mt-3 rounded-lg bg-panel p-3"><h3 className="m-0 text-[12px] font-semibold">运行 DAG · {currentRun.status}</h3><p className="text-[11px] text-fg-3">{currentRun.graph.goal}</p><ol className="grid gap-1">{currentRun.graph.nodes.map((node) => <li key={node.id} className="text-[11px]">{node.title || node.goal} · {node.status}{node.error && <span className="text-danger"> · {node.error}</span>}</li>)}</ol><p className="text-[10px] text-fg-3">事件 {currentRun.events.length} 条</p></section>}
      </div>
    </div>
  </Dialog>;
}
