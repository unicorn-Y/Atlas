import { useEffect, useMemo, useState } from 'react';
import { FileText, FolderOpen, X } from 'lucide-react';
import type { AgentEvent, AgentRun } from '../../types/runtime';
import type { Artifact } from '../../types/artifact';
import type { AgentCapabilityInfo, SkillInfo, ToolListResponse } from '@atlas/backend-adapter';
import { buildTimeline, duration, shortPath } from '../components/timeline';
import { backend } from '../store/useAtlasStore';
import { cn } from '../ui/cn';
import { Empty } from './panels/Empty';
import ChangesPanel from './panels/ChangesPanel';
import FilesPanel from './panels/FilesPanel';
import TerminalPanel from './panels/TerminalPanel';

export type InspectorTab = 'artifacts' | 'activity' | 'changes' | 'files' | 'terminal' | 'context';

const RUN_LABEL: Record<string, string> = { running: '正在处理', planning: '正在规划', waiting: '等你确认', paused: '已暂停', completed: '已完成', failed: '出错了', cancelled: '已停止', idle: '空闲' };
// Diffs, file trees and a shell need room; the reading tabs keep the narrow column.
const WIDE: InspectorTab[] = ['changes', 'files', 'terminal'];

export default function Inspector({ tab, onTab, onClose, run, artifacts, conversationTitle, modelName, tools, skills, activeSkills, capabilities, apiBaseUrl, connected, onToast, workspace, onChooseWorkspace }: {
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
  workspace?: string | null;
  onChooseWorkspace: () => void;
}) {
  const [selected, setSelected] = useState('');
  const [raw, setRaw] = useState(false);
  // The terminal mounts on first visit and then stays, so hiding the tab doesn't end the shell.
  const [terminalOpened, setTerminalOpened] = useState(false);
  useEffect(() => { if (tab === 'terminal') setTerminalOpened(true); }, [tab]);
  const events: AgentEvent[] = run?.events ?? [];
  const steps = useMemo(() => buildTimeline(events).flatMap((item) => item.kind === 'steps' ? item.steps : []), [events]);
  const current = artifacts.find((item) => item.id === selected);
  const refreshKey = `${run?.id}:${run?.status}`;

  const tabs: Array<[InspectorTab, string]> = [
    ['artifacts', `产物${artifacts.length ? ` ${artifacts.length}` : ''}`], ['activity', '步骤'], ['changes', '改动'], ['files', '文件'], ['terminal', '终端'], ['context', '上下文'],
  ];
  return <aside aria-label="任务面板" className={cn('anim-fade flex shrink-0 flex-col shadow-[inset_1px_0_0_var(--line)] transition-[width] duration-200', WIDE.includes(tab) ? 'w-[480px]' : 'w-[340px]')}>
    <div className="flex items-center gap-4 px-5 pt-3 shadow-[inset_0_-1px_0_var(--line)]" role="tablist">
      {tabs.map(([id, label]) =>
        <button key={id} role="tab" aria-selected={tab === id} onClick={() => onTab(id)}
          className={cn('shrink-0 pb-2.5 text-[13px] transition-colors', tab === id ? 'font-medium text-fg shadow-[inset_0_-2px_0_var(--brand)]' : 'text-fg-3 hover:text-fg')}>{label}</button>)}
      <button aria-label="收起任务面板" onClick={onClose} className="-mt-2 ml-auto grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={15} /></button>
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

      {tab === 'changes' && <ChangesPanel runId={run?.id} runStatus={run?.status} apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} />}

      {tab === 'files' && <FilesPanel workspace={workspace} onChooseWorkspace={onChooseWorkspace} refreshKey={refreshKey} />}

      {terminalOpened && <div className={cn('h-full', tab !== 'terminal' && 'hidden')}>
        {workspace || !connected ? connected
          ? <TerminalPanel cwd={workspace!} active={tab === 'terminal'} />
          : <Empty title="后端没有连接" body="连上 Atlas 后端后才能打开终端。" />
          : <Empty title="先选工作目录" body="终端会在这个会话的工作目录里打开。" icon={<FolderOpen size={22} />}
            action={<button onClick={onChooseWorkspace} className="primary-fill inline-flex h-8 items-center gap-2 rounded-[9px] px-3.5 text-[13px] font-medium"><FolderOpen size={15} />选择文件夹</button>} />}
      </div>}

      {tab === 'context' && <ContextTab conversationTitle={conversationTitle} modelName={modelName} run={run} tools={tools} skills={skills} activeSkills={activeSkills}
        capabilities={capabilities} workspace={workspace} onChooseWorkspace={onChooseWorkspace} connected={connected} />}
    </div>
  </aside>;
}

function ContextTab({ conversationTitle, modelName, run, tools, skills, activeSkills, capabilities, workspace, onChooseWorkspace, connected }: {
  conversationTitle?: string; modelName: string; run?: AgentRun; tools: ToolListResponse['tools']; skills: SkillInfo[]; activeSkills: string[];
  capabilities: AgentCapabilityInfo[]; workspace?: string | null; onChooseWorkspace: () => void; connected: boolean;
}) {
  const [rules, setRules] = useState<Array<{ path: string; bytes: number }> | null>(null);
  useEffect(() => {
    if (!workspace || !connected) { setRules(null); return; }
    let stale = false;
    backend.getWorkspaceRules(workspace).then((files) => { if (!stale) setRules(files); }).catch(() => { if (!stale) setRules(null); });
    return () => { stale = true; };
  }, [workspace, connected]);
  const latestUsage = [...(run?.events ?? [])].reverse().find((event) => event.type === 'run.usage')?.data;
  const context = typeof latestUsage?.context_tokens === 'number' && typeof latestUsage?.context_limit === 'number' && latestUsage.context_limit > 0
    ? `${Math.round(latestUsage.context_tokens / latestUsage.context_limit * 100)}%（${latestUsage.context_tokens} / ${latestUsage.context_limit}）` : '—';

  return <div className="grid gap-5 text-[13px]">
    <dl className="m-0 grid gap-2.5">
      {[['任务', conversationTitle ?? '未选择'], ['模型', modelName], ['状态', run ? RUN_LABEL[run.status] ?? run.status : '空闲'], ['上下文占用', context], ['可用工具', `${tools.length} 个`]].map(([label, value]) =>
        <div key={label} className="flex justify-between gap-4"><dt className="text-fg-3">{label}</dt><dd className="m-0 min-w-0 truncate text-right text-fg">{value}</dd></div>)}
    </dl>
    <section>
      <h3 className="m-0 mb-2 text-[12.5px] font-semibold text-fg-2">工作目录</h3>
      <button onClick={onChooseWorkspace} title={workspace ?? undefined} className="flex w-full items-center gap-2 rounded-xl bg-sunken px-3 py-2.5 text-left text-fg-2 hover:text-fg">
        <FolderOpen size={15} className="shrink-0 text-brand" /><span className="min-w-0 truncate">{workspace ?? '没有指定，点这里选择'}</span>
      </button>
      {rules && <p className="m-0 mt-2 text-[12px] leading-[1.6] text-fg-3">
        {rules.length ? <>会读取的规则文件：{rules.map((file) => shortPath(file.path)).join('、')}</> : '这个目录里没有 AGENTS.md、CLAUDE.md 或 .atlas/rules.md。'}
      </p>}
    </section>
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
  </div>;
}
