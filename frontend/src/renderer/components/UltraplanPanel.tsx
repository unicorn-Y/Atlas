import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';

type Step = { id: string; title: string; detail: string; files: string[]; verify: string; annotation?: string };
type Plan = { goal: string; background: string; steps: Step[]; risks: string[]; open_questions: string[] };
type Job = { id: string; status: string; progress: Array<{ title: string; status: string; detail: string }>; plan?: Plan; path?: string; error?: string; steps?: Array<{ id: string; status: string; error?: string }> };

export default function UltraplanPanel({ open, goal, apiBaseUrl, workspace, conversationId, model, onClose, onToast, onOpenArtifact }: {
  open: boolean; goal: string; apiBaseUrl: string; workspace: string; conversationId: string; model: string;
  onClose: () => void; onToast: (message: string) => void; onOpenArtifact: (path: string, goal: string) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const openedArtifact = useRef('');
  useEffect(() => {
    if (!open || !goal || !workspace || !conversationId) return;
    let live = true;
    setBusy(true); setFailure(''); setJob(null);
    void api<Job>(apiBaseUrl, '/api/ultraplan', { method: 'POST', json: { goal, workspace, conversation_id: conversationId, model } })
      .then((started) => { if (live) setJob(started); })
      .catch((error) => { if (live) setFailure(error instanceof Error ? error.message : String(error)); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [open, goal, workspace, conversationId, model, apiBaseUrl]);
  useEffect(() => {
    if (!job || !['researching', 'planning', 'executing'].includes(job.status)) return;
    const timer = window.setInterval(() => { void api<Job>(apiBaseUrl, `/api/ultraplan/${job.id}`).then(setJob).catch(() => undefined); }, 1200);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, apiBaseUrl]);
  useEffect(() => {
    if (job?.status === 'awaiting_approval' && job.path && openedArtifact.current !== job.path) {
      openedArtifact.current = job.path;
      onOpenArtifact(job.path, job.plan?.goal ?? goal);
    }
  }, [job?.status, job?.path, job?.plan?.goal, goal, onOpenArtifact]);
  const change = (update: (plan: Plan) => Plan) => setJob((current) => current?.plan ? { ...current, plan: update(current.plan) } : current);
  const persist = async () => {
    if (!job?.plan) return;
    setJob(await api<Job>(apiBaseUrl, `/api/ultraplan/${job.id}`, { method: 'PUT', json: { plan: job.plan } }));
  };
  const approve = async () => {
    if (!job) return;
    setBusy(true);
    try { await persist(); setJob(await api<Job>(apiBaseUrl, `/api/ultraplan/${job.id}/approve`, { method: 'POST' })); }
    catch (error) { onToast(`无法批准计划：${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); }
  };
  const discard = async () => { if (job) await api(apiBaseUrl, `/api/ultraplan/${job.id}/discard`, { method: 'POST' }).catch(() => undefined); onClose(); };
  const reorder = (from: number, to: number) => change((plan) => {
    if (from === to || from < 0 || to < 0 || from >= plan.steps.length || to >= plan.steps.length) return plan;
    const steps = [...plan.steps]; const [step] = steps.splice(from, 1); steps.splice(to, 0, step); return { ...plan, steps };
  });
  const updateStep = (index: number, patch: Partial<Step>) => change((plan) => ({ ...plan, steps: plan.steps.map((step, i) => i === index ? { ...step, ...patch } : step) }));
  return <Dialog open={open} onOpenChange={(value) => { if (!value) onClose(); }} label="高级计划" className="top-[4vh] max-h-[92vh] w-[min(900px,94vw)] -translate-y-0 overflow-y-auto border border-line bg-panel p-5 shadow-xl">
    <div className="flex items-start justify-between gap-4"><div><h2 className="m-0 text-lg font-semibold text-heading">高级计划</h2><div className="mt-1 flex items-center gap-3 text-xs text-fg-3"><span>{job?.path ?? '并行调研后生成结构化计划'}</span>{job?.path && <button className="text-brand hover:underline" onClick={() => onOpenArtifact(job.path!, job.plan?.goal ?? goal)}>在产物面板打开计划</button>}</div></div><Button size="sm" variant="ghost" onClick={onClose}>关闭</Button></div>
    {(busy || ['researching', 'planning'].includes(job?.status ?? '')) && <p role="status" className="mt-4 rounded-lg bg-sunken p-3 text-sm">正在准备计划…</p>}
    {failure && <p role="alert" className="mt-4 text-sm text-danger">{failure}</p>}{job?.error && <p role="alert" className="mt-4 text-sm text-danger">{job.error}</p>}
    {!!job?.progress.length && <section className="mt-4 rounded-lg bg-sunken p-3"><h3 className="m-0 mb-2 text-sm">并行调研进度</h3><div className="grid gap-2">{job.progress.map((item, index) => <div key={`${item.title}-${index}`} className="text-xs"><b>{item.status === 'completed' ? '✓' : item.status === 'failed' ? '!' : '…'} {item.title}</b><div className="mt-1 whitespace-pre-wrap text-fg-3">{item.detail}</div></div>)}</div></section>}
    {job?.plan && <div className="mt-4 grid gap-4">
      <label className="grid gap-1 text-xs text-fg-3">计划目标<input className="rounded-lg border border-line bg-sunken px-3 py-2 text-sm text-fg" value={job.plan.goal} onChange={(e) => change((p) => ({ ...p, goal: e.target.value }))} /></label>
      <label className="grid gap-1 text-xs text-fg-3">背景<textarea className="min-h-16 rounded-lg border border-line bg-sunken px-3 py-2 text-sm text-fg" value={job.plan.background} onChange={(e) => change((p) => ({ ...p, background: e.target.value }))} /></label>
      <div className="grid gap-3"><div className="flex items-center justify-between"><h3 className="m-0 text-sm">步骤</h3><Button size="sm" variant="secondary" onClick={() => change((p) => ({ ...p, steps: [...p.steps, { id: `step-${Date.now()}`, title: '新步骤', detail: '请填写步骤说明', files: [], verify: '请填写验证方法', annotation: '' }] }))}>添加步骤</Button></div>
        {job.plan.steps.map((step, index) => <section key={step.id} draggable onDragStart={() => setDragIndex(index)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (dragIndex !== null) reorder(dragIndex, index); setDragIndex(null); }} onDragEnd={() => setDragIndex(null)} className={`rounded-xl border p-3 ${job.steps?.[index]?.status === 'failed' ? 'border-danger bg-danger/5' : 'border-line bg-sunken'} ${dragIndex === index ? 'opacity-50' : ''}`}>
          <div className="mb-2 flex items-center gap-2"><span className="text-xs text-fg-3">{job.steps?.[index]?.status === 'completed' ? '✓ 已完成' : job.steps?.[index]?.status === 'failed' ? '执行失败' : `${index + 1}.`}</span><input aria-label="步骤标题" className="min-w-0 flex-1 rounded border border-line bg-panel px-2 py-1 text-sm" value={step.title} onChange={(e) => updateStep(index, { title: e.target.value })} /><Button size="sm" variant="ghost" disabled={!index} onClick={() => reorder(index, index - 1)}>↑</Button><Button size="sm" variant="ghost" disabled={index === job.plan!.steps.length - 1} onClick={() => reorder(index, index + 1)}>↓</Button><Button size="sm" variant="ghost" onClick={() => change((p) => ({ ...p, steps: p.steps.filter((_, i) => i !== index) }))}>删除</Button></div>
          <textarea aria-label="步骤详情" className="min-h-16 w-full rounded border border-line bg-panel px-2 py-1 text-sm" value={step.detail} onChange={(e) => updateStep(index, { detail: e.target.value })} />
          <div className="mt-2 grid gap-2 md:grid-cols-2"><label className="grid gap-1 text-xs text-fg-3">文件路径<input className="rounded border border-line bg-panel px-2 py-1 text-sm text-fg" value={step.files.join(', ')} onChange={(e) => updateStep(index, { files: e.target.value.split(',').map((part) => part.trim()).filter(Boolean) })} /></label><label className="grid gap-1 text-xs text-fg-3">验证方法<input className="rounded border border-line bg-panel px-2 py-1 text-sm text-fg" value={step.verify} onChange={(e) => updateStep(index, { verify: e.target.value })} /></label></div>
          <label className="mt-2 grid gap-1 text-xs text-fg-3">步骤批注<textarea className="min-h-12 rounded border border-line bg-panel px-2 py-1 text-sm text-fg" value={step.annotation ?? ''} onChange={(e) => updateStep(index, { annotation: e.target.value })} /></label>
          {job.steps?.[index]?.error && <p className="mb-0 text-xs text-danger">{job.steps[index].error}</p>}
        </section>)}</div>
      <StringList title="风险" values={job.plan.risks} onChange={(risks) => change((p) => ({ ...p, risks }))} /><StringList title="待确认问题" values={job.plan.open_questions} onChange={(open_questions) => change((p) => ({ ...p, open_questions }))} />
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => void discard()}>放弃</Button><Button variant="secondary" onClick={() => void persist()}>保存修改</Button><Button disabled={busy || job.status === 'executing'} onClick={() => void approve()}>{job.status === 'failed_step' ? '继续执行' : '批准并执行'}</Button></div>
      {job.status === 'completed' && <p className="mb-0 text-sm text-success">所有步骤已完成。</p>}
    </div>}
  </Dialog>;
}

function StringList({ title, values, onChange }: { title: string; values: string[]; onChange: (values: string[]) => void }) {
  return <label className="grid gap-1 text-xs text-fg-3">{title}<textarea className="min-h-14 rounded-lg border border-line bg-sunken px-3 py-2 text-sm text-fg" value={values.join('\n')} onChange={(event) => onChange(event.target.value.split('\n').filter((value) => value.trim()))} /></label>;
}
