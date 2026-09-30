import { useEffect, useMemo, useState } from 'react';
import { FileText, History, LoaderCircle, RotateCcw, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';
import type { AgentEvent, AgentRun } from '../../types/runtime';
import type { Artifact } from '../../types/artifact';
import type { AgentCapabilityInfo, SkillInfo, ToolListResponse } from '@atlas/backend-adapter';
import { buildTimeline, duration } from '../components/timeline';
import { cn } from '../ui/cn';

export type InspectorTab = 'artifacts' | 'activity' | 'checkpoints' | 'context';

interface Checkpoint { id: string; workspace: string; created_at: string; file_count: number }

const RUN_LABEL: Record<string, string> = { running: '正在处理', planning: '正在规划', waiting: '等你确认', paused: '已暂停', completed: '已完成', failed: '出错了', cancelled: '已停止', idle: '空闲' };

export default function Inspector({ tab, onTab, onClose, run, artifacts, conversationTitle, modelName, tools, skills, activeSkills, capabilities, apiBaseUrl, connected, onToast }: {
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
  run?: AgentRun;
  artifacts: Artifact[];
  conversationTitle?: string;
  modelName: string;
  tools: ToolListResponse['tools'];
  skills: SkillInfo[];
  activeSkills: string[];
  capabilities: AgentCapabilityInfo[];
  apiBaseUrl: string;
  connected: boolean;
  onToast: (text: string) => void;
}) {
  const [selected, setSelected] = useState('');
  const [raw, setRaw] = useState(false);
  const events: AgentEvent[] = run?.events ?? [];
  const steps = useMemo(() => buildTimeline(events).flatMap((item) => item.kind === 'steps' ? item.steps : []), [events]);
  const current = artifacts.find((item) => item.id === selected);

  return <aside aria-label="任务面板" className="anim-fade flex w-[340px] shrink-0 flex-col shadow-[inset_1px_0_0_var(--line)]">
    <div className="flex items-center gap-5 px-5 pt-3 shadow-[inset_0_-1px_0_var(--line)]" role="tablist">
      {([['artifacts', `产物${artifacts.length ? ` ${artifacts.length}` : ''}`], ['activity', '步骤'], ['checkpoints', '恢复'], ['context', '上下文']] as Array<[InspectorTab, string]>).map(([id, label]) =>
        <button key={id} role="tab" aria-selected={tab === id} onClick={() => onTab(id)}
          className={cn('pb-2.5 text-[13px] transition-colors', tab === id ? 'font-medium text-fg shadow-[inset_0_-2px_0_var(--brand)]' : 'text-fg-3 hover:text-fg')}>{label}</button>)}
      <button aria-label="收起任务面板" onClick={onClose} className="-mt-2 ml-auto grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={15} /></button>
    </div>

    <div className="min-h-0 flex-1 overflow-auto p-5">
      {tab === 'artifacts' && (artifacts.length ? <div className="grid gap-2">
        {artifacts.map((artifact) => <button key={artifact.id} onClick={() => setSelected(artifact.id === selected ? '' : artifact.id)}
          className={cn('card-surface flex items-start gap-3 rounded-xl p-3 text-left', selected === artifact.id && 'shadow-[inset_0_0_0_1px_var(--brand)]')}>
          <FileText size={16} className="mt-0.5 shrink-0 text-brand" />
          <span className="min-w-0"><b className="block truncate text-[13.5px] font-medium text-fg">{artifact.name}</b><small className="block truncate text-[12px] text-fg-3">{artifact.path ?? artifact.type}</small></span>
        </button>)}
        {current?.summary && <p className="mt-2 rounded-xl bg-sunken p-3 text-[13px] leading-[1.7] text-fg-2">{current.summary}</p>}
      </div> : <Empty title="还没有产物" body="Atlas 写出或改动的文件、生成的报告会出现在这里。" />)}

      {tab === 'activity' && (run ? <>
        {steps.length ? <ol className="m-0 grid list-none gap-2.5 p-0">
          {steps.map((step) => <li key={step.id} className="grid grid-cols-[10px_minmax(0,1fr)] gap-2.5 text-[13px]">
            <span className={cn('mt-[7px] size-2 rounded-full', step.state === 'failed' ? 'bg-danger' : step.state === 'running' ? 'bg-brand' : 'bg-ok')} />
            <span className="min-w-0"><span className="text-fg">{step.verb}</span>{step.target && <code className="ml-1.5 break-all font-mono text-[11.5px] text-fg-2">{step.target}</code>}
              <small className="block text-[11.5px] text-fg-3">{new Date(step.startedAt).toLocaleTimeString()}{step.endedAt ? `，${duration(step.startedAt, step.endedAt)}` : ''}</small></span>
          </li>)}
        </ol> : <Empty title="这次没有调用工具" body="Atlas 直接回答了，没有读文件或运行命令。" />}
        <button onClick={() => setRaw((value) => !value)} className="mt-5 text-[12px] text-fg-3 underline decoration-line-strong underline-offset-[3px] hover:text-fg">{raw ? '收起原始事件' : `查看原始事件（${events.length}）`}</button>
        {raw && <ul className="mt-2 grid list-none gap-1 p-0 font-mono text-[11.5px] text-fg-3">{events.map((event) => <li key={event.id} className="truncate">{new Date(event.timestamp).toLocaleTimeString()} {event.type} {String(event.data.name ?? event.data.phase ?? event.data.status ?? '')}</li>)}</ul>}
      </> : <Empty title="还没有开始" body="发出一个任务后，Atlas 做的每一步都会记在这里。" />)}

      {tab === 'checkpoints' && <Checkpoints apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} refreshKey={`${run?.id}:${run?.status}`} />}

      {tab === 'context' && <div className="grid gap-5 text-[13px]">
        <dl className="m-0 grid gap-2.5">
          {[['任务', conversationTitle ?? '未选择'], ['模型', modelName], ['状态', run ? RUN_LABEL[run.status] ?? run.status : '空闲'], ['可用工具', `${tools.length} 个`]].map(([label, value]) =>
            <div key={label} className="flex justify-between gap-4"><dt className="text-fg-3">{label}</dt><dd className="m-0 min-w-0 truncate text-right text-fg">{value}</dd></div>)}
        </dl>
        <section>
          <h3 className="m-0 mb-2 text-[12.5px] font-semibold text-fg-2">这次任务用到的技能</h3>
          <p className="m-0 text-fg-2">{activeSkills.join('、') || '没有指定，Atlas 会自己判断。'}</p>
        </section>
        {skills.length > 0 && <section>
          <h3 className="m-0 mb-2 text-[12.5px] font-semibold text-fg-2">已安装技能 {skills.length}</h3>
          <div className="grid gap-2">{skills.map((skill) => <div key={skill.name} className="rounded-xl bg-sunken px-3 py-2.5">
            <b className="text-[13px] font-medium text-fg">{skill.name}</b><p className="m-0 mt-0.5 line-clamp-2 text-[12px] leading-[1.55] text-fg-3">{skill.description}</p>
          </div>)}</div>
        </section>}
        {capabilities.length > 0 && <section>
          <h3 className="m-0 mb-2 text-[12.5px] font-semibold text-fg-2">扩展能力 {capabilities.length}</h3>
          <div className="flex flex-wrap gap-1.5">{capabilities.map((capability) => <span key={capability.name} title={capability.description} className="rounded-md bg-sunken px-2 py-0.5 text-[12px] text-fg-2">{capability.name}</span>)}</div>
        </section>}
      </div>}
    </div>
  </aside>;
}

/** Shadow snapshots Atlas takes before changing files; restoring one puts those files back. */
function Checkpoints({ apiBaseUrl, connected, onToast, refreshKey }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void; refreshKey: string }) {
  const [items, setItems] = useState<Checkpoint[] | null>(null);
  const [confirm, setConfirm] = useState('');
  const [restoring, setRestoring] = useState('');
  const [error, setError] = useState('');
  const invoke = <T,>(name: string, inputs: Record<string, unknown> = {}) =>
    api<{ result: T }>(apiBaseUrl, `/api/agent/capabilities/${name}/invoke`, { method: 'POST', json: inputs }).then((body) => body.result);
  useEffect(() => {
    if (!connected) return;
    let stale = false;
    invoke<Checkpoint[]>('workspace.checkpoint.list')
      .then((result) => { if (!stale) { setItems([...result].sort((a, b) => b.created_at.localeCompare(a.created_at))); setError(''); } })
      .catch((exc) => { if (!stale) { setItems([]); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [apiBaseUrl, connected, refreshKey]);

  const restore = async (checkpoint: Checkpoint) => {
    if (confirm !== checkpoint.id) { setConfirm(checkpoint.id); return; }
    setConfirm('');
    setRestoring(checkpoint.id);
    try {
      const result = await invoke<{ restored?: unknown[] }>('workspace.checkpoint.restore', { checkpoint_id: checkpoint.id });
      onToast(`已恢复 ${Array.isArray(result.restored) ? result.restored.length : checkpoint.file_count} 个文件`);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setRestoring(''); }
  };

  if (!connected) return <Empty title="后端没有连接" body="连上 Atlas 后端后才能查看快照。" />;
  if (items === null) return <p className="py-8 text-center text-[13px] text-fg-3">正在读取快照…</p>;
  return <div className="grid gap-2">
    <p className="m-0 mb-1 text-[12.5px] leading-[1.6] text-fg-3">Atlas 改文件之前会先存一份快照。恢复只还原这些文件，不会撤销命令、网络请求或数据库改动。</p>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
    {items.map((checkpoint) => <div key={checkpoint.id} className="card-surface flex items-center gap-3 rounded-xl p-3">
      <History size={16} className="shrink-0 text-fg-3" />
      <span className="min-w-0 flex-1">
        <b className="block truncate text-[13px] font-medium text-fg" title={checkpoint.workspace}>{checkpoint.workspace.split(/[\\/]/).filter(Boolean).pop() ?? checkpoint.workspace}</b>
        <small className="block text-[12px] text-fg-3">{relativeTime(checkpoint.created_at)}，{checkpoint.file_count} 个文件</small>
      </span>
      <button onClick={() => void restore(checkpoint)} disabled={Boolean(restoring)}
        className={cn('inline-flex h-7 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] disabled:opacity-50', confirm === checkpoint.id ? 'bg-danger-soft text-danger' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
        {restoring === checkpoint.id ? <LoaderCircle size={13} className="spin" /> : <RotateCcw size={13} />}{confirm === checkpoint.id ? '确认恢复' : '恢复'}
      </button>
    </div>)}
    {!items.length && !error && <Empty title="还没有快照" body="Atlas 修改文件时会自动留一份，出了问题可以在这里退回去。" />}
  </div>;
}

function Empty({ title, body }: { title: string; body: string }) {
  return <div className="px-2 py-10 text-center"><b className="block text-[14px] font-medium text-fg">{title}</b><p className="m-0 mt-1 text-[13px] leading-[1.6] text-fg-3">{body}</p></div>;
}
