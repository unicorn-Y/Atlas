import { useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { FileText, FolderOpen, GitBranch, GitMerge, Trash2, X } from 'lucide-react';
import type { ConversationMessage, WorktreeInfo } from '@atlas/backend-adapter';
import type { AgentEvent, AgentRun } from '../../types/runtime';
import type { Artifact } from '../../types/artifact';
import type { AgentCapabilityInfo, SkillInfo, ToolListResponse } from '@atlas/backend-adapter';
import { buildTimeline, duration, shortPath } from '../components/timeline';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import { cn } from '../ui/cn';
import { Empty } from './panels/Empty';
import ChangesPanel from './panels/ChangesPanel';
import FilesPanel from './panels/FilesPanel';
import SpecsPanel from './panels/SpecsPanel';
import TerminalPanel from './panels/TerminalPanel';
import BrowserPanel, { type PickedElement } from './panels/BrowserPanel';
import ProcessesPanel from './panels/ProcessesPanel';
import PullRequestSection from './panels/PullRequestSection';
import SessionDashboardPanel from './panels/SessionDashboardPanel';

export type InspectorTab = 'artifacts' | 'activity' | 'changes' | 'files' | 'specs' | 'terminal' | 'browser' | 'context' | 'processes' | 'dashboard';

const EMPTY_MESSAGES: ConversationMessage[] = [];
const RUN_LABEL: Record<string, string> = { running: '正在处理', planning: '正在规划', waiting: '等你确认', paused: '已暂停', completed: '已完成', failed: '出错了', cancelled: '已停止', idle: '空闲' };
const terminalCommandOwners = new Map<string, string>();
function commandForConversation(command: { id: string; text: string } | null, conversationId: string) {
  if (!command || !conversationId) return command;
  const owner = terminalCommandOwners.get(command.id);
  if (owner) return owner === conversationId ? command : null;
  terminalCommandOwners.set(command.id, conversationId);
  if (terminalCommandOwners.size > 100) terminalCommandOwners.delete(terminalCommandOwners.keys().next().value!);
  return command;
}
// Diffs, file trees and a shell need room; the reading tabs keep the narrow column.
const WIDE: InspectorTab[] = ['changes', 'files', 'specs', 'terminal', 'browser'];
const WIDTH_KEY = 'atlas.preference.inspector-width';
const readWidth = () => { try { const value = Number(localStorage.getItem(WIDTH_KEY)); return value >= 300 ? value : null; } catch { return null; } };

/** Drag the panel's left edge to set its width (kept on this machine); double-click goes back to automatic. */
function useResizableWidth() {
  const [width, setWidth] = useState<number | null>(readWidth);
  const [dragging, setDragging] = useState(false);
  const start = (event: ReactPointerEvent<HTMLDivElement>) => {
    const panel = event.currentTarget.parentElement;
    if (!panel) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = panel.getBoundingClientRect().width;
    let latest = startWidth;
    let moved = false;
    const move = (moveEvent: PointerEvent) => {
      // A click (or the two of a double-click) is not a drag: start only once the pointer travels.
      if (!moved && Math.abs(moveEvent.clientX - startX) < 3) return;
      if (!moved) { moved = true; setDragging(true); }
      latest = Math.round(Math.min(window.innerWidth * 0.62, Math.max(300, startWidth + startX - moveEvent.clientX)));
      setWidth(latest);
    };
    const end = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      if (moved) try { localStorage.setItem(WIDTH_KEY, String(latest)); } catch { /* storage unavailable */ }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
  };
  const reset = () => { setWidth(null); try { localStorage.removeItem(WIDTH_KEY); } catch { /* storage unavailable */ } };
  return { width, dragging, start, reset };
}

export default function Inspector({ tab, onTab, onClose, run, artifacts, conversationTitle, modelName, tools, skills, activeSkills, capabilities, apiBaseUrl, connected, onToast, workspace, onChooseWorkspace, browserUrl, onBrowserUrl, browserSuggestions, onPick, terminalCommand, onSendToAtlas, onPreview, conversationId, worktree, onWorktreeChanged, onAsk }: {
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
  browserUrl: string;
  onBrowserUrl: (url: string) => void;
  browserSuggestions: string[];
  onPick: (picked: PickedElement) => void;
  terminalCommand: { id: string; text: string } | null;
  onSendToAtlas: (text: string) => void;
  onPreview: (url: string) => void;
  conversationId: string;
  worktree: { path: string; branch: string; base: string } | null;
  onWorktreeChanged: () => void;
  onAsk: (text: string) => void;
}) {
  const [selected, setSelected] = useState('');
  const [raw, setRaw] = useState(false);
  // The terminal mounts on first visit and then stays, so hiding the tab doesn't end the shell.
  const [terminalOpened, setTerminalOpened] = useState(false);
  const [browserOpened, setBrowserOpened] = useState(false);
  useEffect(() => { if (tab === 'terminal') setTerminalOpened(true); if (tab === 'browser') setBrowserOpened(true); }, [tab]);
  const messages: ConversationMessage[] = useAtlasStore((state) => state.conversationMessages[conversationId]) ?? EMPTY_MESSAGES;
  const conversationRuns = useAtlasStore((state) => state.runs);
  const events: AgentEvent[] = run?.events ?? [];
  const steps = useMemo(() => buildTimeline(events).flatMap((item) => item.kind === 'steps' ? item.steps : []), [events]);
  const dashboardSteps = useMemo(() => conversationRuns.filter((item) => item.conversationId === conversationId)
    .flatMap((item) => buildTimeline(item.events).flatMap((entry) => entry.kind === 'steps' ? entry.steps : [])), [conversationRuns, conversationId]);
  const current = artifacts.find((item) => item.id === selected);
  const refreshKey = `${run?.id}:${run?.status}`;
  const scopedTerminalCommand = commandForConversation(terminalCommand, conversationId);

  const resize = useResizableWidth();
  const tabs: Array<[InspectorTab, string]> = [
    ['artifacts', `产物${artifacts.length ? ` ${artifacts.length}` : ''}`], ['activity', '步骤'], ['changes', '改动'], ['files', '文件'], ['specs', '规格'], ['terminal', '终端'], ['browser', '浏览器'], ['context', '上下文'], ['processes', '进程'], ['dashboard', '看板'],
  ];
  return <aside aria-label="任务面板" style={resize.width ? { width: resize.width } : undefined}
    className={cn('anim-fade relative flex shrink-0 flex-col shadow-[inset_1px_0_0_var(--line)]', !resize.dragging && 'transition-[width] duration-200', !resize.width && (WIDE.includes(tab) ? 'w-[480px]' : 'w-[340px]'))}>
    <div role="separator" aria-orientation="vertical" aria-label="拖动调整任务面板宽度，双击恢复自动" title="拖动调整宽度，双击恢复自动"
      onPointerDown={resize.start} onDoubleClick={resize.reset}
      className={cn('absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize after:absolute after:inset-y-0 after:left-[3px] after:w-0.5 after:rounded-full after:transition-colors hover:after:bg-brand/50', resize.dragging && 'after:bg-brand')} />
    {/* While dragging, keep the embedded browser from swallowing the pointer. */}
    {resize.dragging && <div className="fixed inset-0 z-50 cursor-col-resize" />}
    <div className="flex items-center gap-2 pr-2 pl-4 pt-3 shadow-[inset_0_-1px_0_var(--line)]">
      <div className="flex min-w-0 flex-1 items-center gap-3.5 overflow-x-auto [scrollbar-width:none]" role="tablist">
      {tabs.map(([id, label]) =>
        <button key={id} role="tab" aria-selected={tab === id} onClick={() => onTab(id)}
          className={cn('shrink-0 pb-2.5 text-[13px] transition-colors', tab === id ? 'font-medium text-fg shadow-[inset_0_-2px_0_var(--brand)]' : 'text-fg-3 hover:text-fg')}>{label}</button>)}
      </div>
      <button aria-label="收起任务面板" onClick={onClose} className="-mt-2 grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={15} /></button>
    </div>

    <div className="min-h-0 flex-1 overflow-auto p-5">
      {tab === 'artifacts' && (artifacts.length ? <div className="grid gap-2">
        {artifacts.map((artifact) => <button key={artifact.id} onClick={() => setSelected(artifact.id === selected ? '' : artifact.id)}
          className={cn('card-surface flex items-start gap-3 rounded-xl p-3 text-left', selected === artifact.id && 'shadow-[inset_0_0_0_1px_var(--brand)]')}>
          <FileText size={16} className="mt-0.5 shrink-0 text-brand" />
          <span className="min-w-0"><b className="block truncate text-[13.5px] font-medium text-fg">{artifact.name}</b><small className="block truncate text-[12px] text-fg-3">{artifact.path ?? artifact.type}</small></span>
        </button>)}
        {current?.summary && <p className="mt-2 rounded-xl bg-sunken p-3 text-[13px] leading-[1.7] text-fg-2">{current.summary}</p>}
        {current?.path && <ArtifactActions path={current.path} root={worktree?.path ?? workspace ?? ''} onPreview={onPreview} />}
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

      {tab === 'changes' && <ChangesPanel runId={run?.id} runStatus={run?.status} apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} onAsk={onAsk} />}

      {tab === 'specs' && <SpecsPanel workspace={worktree?.path ?? workspace} onChooseWorkspace={onChooseWorkspace} refreshKey={refreshKey} onAsk={onAsk} />}
      {tab === 'files' && <FilesPanel workspace={worktree?.path ?? workspace} onChooseWorkspace={onChooseWorkspace} refreshKey={refreshKey} onPreview={onPreview} />}

      {terminalOpened && <div className={cn('h-full', tab !== 'terminal' && 'hidden')}>
        {workspace || !connected ? connected
          ? workspace!.startsWith('ssh://')
            ? <Empty title="远程目录暂时不能开终端" body="终端面板只能打开这台电脑上的 PowerShell。远程目录里的命令可以直接让 Atlas 去运行。" />
            : <TerminalPanel conversationId={conversationId} cwd={workspace!} active={tab === 'terminal'} command={scopedTerminalCommand} onSendToAtlas={onSendToAtlas} />
          : <Empty title="后端没有连接" body="连上 Atlas 后端后才能打开终端。" />
          : <Empty title="先选工作目录" body="终端会在这个会话的工作目录里打开。" icon={<FolderOpen size={22} />}
            action={<button onClick={onChooseWorkspace} className="primary-fill inline-flex h-8 items-center gap-2 rounded-[9px] px-3.5 text-[13px] font-medium"><FolderOpen size={15} />选择文件夹</button>} />}
      </div>}

      {browserOpened && <div className={cn('h-full', tab !== 'browser' && 'hidden')}>
        <BrowserPanel url={browserUrl} onUrl={onBrowserUrl} suggestions={browserSuggestions} onPick={onPick} onToast={onToast} onAsk={onAsk}
          apiBaseUrl={apiBaseUrl} runId={run?.id} events={events} />
      </div>}

      {tab === 'processes' && <ProcessesPanel onToast={onToast} />}

      {tab === 'dashboard' && <SessionDashboardPanel apiBaseUrl={apiBaseUrl} conversationId={conversationId} messages={messages} steps={dashboardSteps} />}

      {tab === 'context' && <ContextTab conversationTitle={conversationTitle} modelName={modelName} run={run} tools={tools} skills={skills} activeSkills={activeSkills}
        capabilities={capabilities} workspace={workspace} onChooseWorkspace={onChooseWorkspace} connected={connected}
        conversationId={conversationId} worktree={worktree} onWorktreeChanged={onWorktreeChanged} onToast={onToast} onPreview={onPreview} onAsk={onAsk} />}
    </div>
  </aside>;
}

function ContextTab({ conversationTitle, modelName, run, tools, skills, activeSkills, capabilities, workspace, onChooseWorkspace, connected, conversationId, worktree, onWorktreeChanged, onToast, onPreview, onAsk }: {
  conversationTitle?: string; modelName: string; run?: AgentRun; tools: ToolListResponse['tools']; skills: SkillInfo[]; activeSkills: string[];
  capabilities: AgentCapabilityInfo[]; workspace?: string | null; onChooseWorkspace: () => void; connected: boolean;
  conversationId: string; worktree: { path: string; branch: string; base: string } | null; onWorktreeChanged: () => void; onToast: (text: string) => void;
  onPreview: (url: string) => void; onAsk: (text: string) => void;
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
  const breakdown = latestUsage?.context_breakdown as { categories?: Array<{ id: string; label: string; tokens: number }>; context_max?: number; context_used?: number } | undefined;

  // minmax(0,1fr): long unbroken paths must truncate, not widen the column past the panel.
  return <div className="grid grid-cols-[minmax(0,1fr)] gap-5 text-[13px]">
    <dl className="m-0 grid grid-cols-[minmax(0,1fr)] gap-2.5">
      {[['任务', conversationTitle ?? '未选择'], ['模型', modelName], ['状态', run ? RUN_LABEL[run.status] ?? run.status : '空闲'], ['上下文占用', context], ['可用工具', `${tools.length} 个`]].map(([label, value]) =>
        <div key={label} className="flex justify-between gap-4"><dt className="shrink-0 text-fg-3">{label}</dt><dd className="m-0 min-w-0 truncate text-right text-fg">{value}</dd></div>)}
    </dl>
    {breakdown?.categories && <section>
      <h3 className="m-0 mb-2 text-[12.5px] font-semibold text-fg-2">上下文构成</h3>
      <div className="grid gap-1.5">
        {breakdown.categories.map((item) => <div key={item.id} className="flex justify-between gap-3 text-[12.5px]">
          <span className="text-fg-3">{item.label}</span><span className="tabular-nums text-fg-2">{item.tokens.toLocaleString()} tokens</span>
        </div>)}
        {typeof breakdown.context_max === 'number' && <div className="mt-1 flex justify-between border-t border-line pt-1.5 text-[12.5px]">
          <span className="text-fg-3">剩余额度</span><span className="tabular-nums text-fg-2">{Math.max(0, breakdown.context_max - (breakdown.context_used ?? 0)).toLocaleString()} tokens</span>
        </div>}
      </div>
    </section>}
    <section>
      <h3 className="m-0 mb-2 text-[12.5px] font-semibold text-fg-2">工作目录</h3>
      <button onClick={onChooseWorkspace} title={workspace ?? undefined} className="flex w-full items-center gap-2 rounded-xl bg-sunken px-3 py-2.5 text-left text-fg-2 hover:text-fg">
        <FolderOpen size={15} className="shrink-0 text-brand" /><span className="min-w-0 truncate">{workspace ?? '没有指定，点这里选择'}</span>
      </button>
      {rules && <p className="m-0 mt-2 text-[12px] leading-[1.6] text-fg-3">
        {rules.length ? <>会读取的规则文件：{rules.map((file) => shortPath(file.path)).join('、')}</> : '这个目录里没有 AGENTS.md、CLAUDE.md 或 .atlas/rules.md。'}
      </p>}
    </section>
    {connected && (worktree?.path ?? workspace) && !String(worktree?.path ?? workspace).startsWith('ssh://') && <PullRequestSection root={String(worktree?.path ?? workspace)}
      refreshKey={`${run?.id}:${run?.status}`} onOpenUrl={onPreview} onAsk={onAsk} />}
    {worktree && <WorktreeSection conversationId={conversationId} worktree={worktree} onChanged={onWorktreeChanged} onToast={onToast} refreshKey={`${run?.id}:${run?.status}`} />}
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

/** A conversation working in its own git worktree: see how far it has drifted, merge it back or drop it. */
function WorktreeSection({ conversationId, worktree, onChanged, onToast, refreshKey }: {
  conversationId: string; worktree: { path: string; branch: string; base: string }; onChanged: () => void; onToast: (text: string) => void; refreshKey: string;
}) {
  const [info, setInfo] = useState<WorktreeInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<'' | 'remove' | 'force'>('');
  useEffect(() => {
    let stale = false;
    backend.getWorktree(conversationId).then((result) => { if (!stale) setInfo(result); }).catch(() => { if (!stale) setInfo(null); });
    return () => { stale = true; };
  }, [conversationId, refreshKey]);
  const act = async (task: () => Promise<unknown>, done: string) => {
    setBusy(true); setError('');
    try { await task(); onToast(done); onChanged(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); setConfirm(''); }
  };
  const changed = Array.isArray(info?.changed_files) ? info!.changed_files.length : info?.changed_files ?? 0;
  return <section>
    <h3 className="m-0 mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-fg-2"><GitBranch size={13} />独立分支</h3>
    <div className="rounded-xl bg-sunken px-3 py-2.5 text-[12.5px] text-fg-2">
      <p className="m-0"><code className="font-mono text-fg">{worktree.branch}</code> 基于 <code className="font-mono">{worktree.base}</code></p>
      {info && <p className="m-0 mt-1 text-fg-3">领先 {info.ahead} 个提交、落后 {info.behind} 个{info.dirty ? `，有 ${changed} 个未提交的改动` : ''}</p>}
      <p className="m-0 mt-1 truncate text-[11.5px] text-fg-3" title={worktree.path}>{worktree.path}</p>
    </div>
    {error && <p role="alert" className="m-0 mt-2 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{error}</p>}
    <div className="mt-2 flex flex-wrap gap-1.5">
      <button disabled={busy} onClick={() => void act(() => backend.mergeWorktree(conversationId, 'squash'), `已把 ${worktree.branch} 压成一个提交合并到 ${worktree.base}`)}
        className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-50"><GitMerge size={13} />压缩合并</button>
      <button disabled={busy} onClick={() => void act(() => backend.mergeWorktree(conversationId, 'merge'), `已合并到 ${worktree.base}`)}
        className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-50"><GitMerge size={13} />普通合并</button>
      <button disabled={busy} onClick={() => {
        if (!confirm) { setConfirm(info?.dirty ? 'force' : 'remove'); return; }
        void act(() => backend.removeWorktree(conversationId, { force: confirm === 'force' }), '已删除独立分支和它的目录');
      }} className={cn('inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[12.5px] disabled:opacity-50', confirm ? 'bg-danger-soft text-danger' : 'text-fg-3 hover:bg-hover hover:text-danger')}>
        <Trash2 size={13} />{confirm === 'force' ? '有未提交改动，确认丢弃并删除' : confirm ? '确认删除' : '删除'}</button>
    </div>
  </section>;
}

const PREVIEWABLE = /\.(html?|pdf|svg|png|jpe?g|gif|webp)$/i;

/** Preview an artifact in the browser panel (when it lives in the working directory) or open it with its default app. */
function ArtifactActions({ path, root, onPreview }: { path: string; root: string; onPreview: (url: string) => void }) {
  const absolute = /^([a-zA-Z]:[\\/]|\\\\|\/)/.test(path);
  const base = root.replace(/[\\/]+$/, '');
  const inside = !absolute || (base && path.toLowerCase().startsWith(base.toLowerCase()));
  const relative = absolute ? path.slice(base.length).replace(/^[\\/]+/, '') : path;
  const full = absolute ? path : `${base}\\${path}`;
  return <div className="flex gap-2">
    {PREVIEWABLE.test(path) && base && inside && <button onClick={() => onPreview(backend.rawFileUrl(base, relative))} className="rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg">在浏览器预览</button>}
    {window.atlasDesktop?.openPath && (absolute || base) && <button onClick={() => void window.atlasDesktop!.openPath(full)} className="rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg">用默认程序打开</button>}
  </div>;
}
