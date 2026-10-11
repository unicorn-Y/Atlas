import { useEffect, useState } from 'react';
import { ArrowUpCircle, Lock, LockOpen, Trash2, X } from 'lucide-react';
import { Button } from '../../ui/Button';
import { Dialog } from '../../ui/Dialog';
import { cn } from '../../ui/cn';
import type { WorkbenchAgent, WorkbenchApi, WorkbenchMode } from '../../services/workbenchApi';

const MODE_LABEL: Record<WorkbenchMode, string> = { acp: 'ACP 对话（推荐）', terminal: '终端界面', command: '一次性命令' };

export const toEnvText = (env: Record<string, string>) => Object.entries(env).map(([k, v]) => `${k}=${v}`).join('\n');
export const fromEnvText = (text: string) => Object.fromEntries(text.split('\n').map((line) => line.trim()).filter((line) => line && !line.startsWith('#') && line.includes('='))
  .map((line) => [line.slice(0, line.indexOf('=')).trim(), line.slice(line.indexOf('=') + 1)]));

export interface ManifestDraft { name: string; description: string; mode: WorkbenchMode; command: string; args: string; env: string; cwd: string; permission: 'ask' | 'allow'; isolate_config: boolean }

export const draftOf = (agent?: WorkbenchAgent): ManifestDraft => ({
  name: agent?.name ?? '', description: agent?.description ?? '', mode: agent?.mode ?? 'acp', command: agent?.command ?? '',
  args: (agent?.args ?? []).join('\n'), env: toEnvText(agent?.env ?? {}), cwd: agent?.cwd ?? '',
  permission: agent?.permission ?? 'ask', isolate_config: agent?.isolate_config ?? false,
});

export const manifestOf = (draft: ManifestDraft): Partial<WorkbenchAgent> => ({
  name: draft.name.trim(), description: draft.description.trim(), mode: draft.mode, command: draft.command.trim(),
  args: draft.args.split('\n').map((line) => line.trim()).filter(Boolean), env: fromEnvText(draft.env), cwd: draft.cwd.trim(),
  permission: draft.permission, isolate_config: draft.isolate_config,
});

const input = 'w-full rounded-lg bg-sunken px-2.5 py-1.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-70';

/** 挂件配置表单；新建和编辑共用。 */
export function ManifestForm({ draft, onChange, disabled }: { draft: ManifestDraft; onChange: (draft: ManifestDraft) => void; disabled?: boolean }) {
  const set = <K extends keyof ManifestDraft>(key: K, value: ManifestDraft[K]) => onChange({ ...draft, [key]: value });
  const row = 'grid gap-1 text-[12.5px] text-fg-2';
  return <div className="grid gap-3">
    <label className={row}>名字<input className={input} disabled={disabled} value={draft.name} onChange={(e) => set('name', e.target.value)} /></label>
    <label className={row}>它专门干什么（说明）<input className={input} disabled={disabled} value={draft.description} onChange={(e) => set('description', e.target.value)} /></label>
    <label className={row}>接入方式
      <select className={input} disabled={disabled} value={draft.mode} onChange={(e) => set('mode', e.target.value as WorkbenchMode)}>
        {(Object.keys(MODE_LABEL) as WorkbenchMode[]).map((mode) => <option key={mode} value={mode}>{MODE_LABEL[mode]}</option>)}
      </select>
      <span className="text-[11.5px] text-fg-3">{draft.mode === 'acp' ? '支持 ACP 协议的 agent：结构化显示对话、工具、改动和权限请求。' : draft.mode === 'terminal' ? '任何命令行 agent：直接嵌一个终端跑它自己的界面。' : '每个任务跑一次命令，参数里的 {prompt} 会换成任务内容。'}</span>
    </label>
    <label className={row}>启动命令<input className={cn(input, 'font-mono')} disabled={disabled} value={draft.command} placeholder="例如 npx、claude、C:\tools\my-agent.exe" onChange={(e) => set('command', e.target.value)} /></label>
    <label className={row}>参数（一行一个；可用 {'{agent_dir}'} {'{workspace}'}{draft.mode === 'command' ? ' {prompt}' : ''}）
      <textarea className={cn(input, 'font-mono')} rows={3} disabled={disabled} value={draft.args} onChange={(e) => set('args', e.target.value)} /></label>
    <label className={row}>环境变量（一行一个 KEY=VALUE；可用 {'{home}'}；只给它自己，和 Atlas 主体无关）
      <textarea className={cn(input, 'font-mono')} rows={4} disabled={disabled} value={draft.env} onChange={(e) => set('env', e.target.value)} /></label>
    <label className={row}>工作目录（留空 = 它自己文件夹里的 workspace）<input className={cn(input, 'font-mono')} disabled={disabled} value={draft.cwd} onChange={(e) => set('cwd', e.target.value)} /></label>
    <label className={row}>它要改文件、跑命令时
      <select className={input} disabled={disabled} value={draft.permission} onChange={(e) => set('permission', e.target.value as 'ask' | 'allow')}>
        <option value="ask">先问我</option><option value="allow">直接允许</option>
      </select></label>
    <label className="flex items-start gap-2 text-[12.5px] text-fg-2">
      <input type="checkbox" className="mt-0.5" disabled={disabled} checked={draft.isolate_config} onChange={(e) => set('isolate_config', e.target.checked)} />
      <span>配置也隔离：Claude / Codex / Gemini 等的配置目录指到它自己的 home 文件夹（要在它的隔离终端里重新登录一次）。不勾 = 共用这台电脑上已有的登录。</span>
    </label>
  </div>;
}

/** 挂件设置：默认锁定，点「解锁编辑」确认后才能改。 */
export default function AgentSettings({ api, agent, open, onOpenChange, onChanged, onDeleted, onToast }: {
  api: WorkbenchApi; agent: WorkbenchAgent; open: boolean; onOpenChange: (open: boolean) => void;
  onChanged: (agent: WorkbenchAgent) => void; onDeleted: () => void; onToast: (text: string) => void;
}) {
  const [unlocked, setUnlocked] = useState(false);
  const [confirmUnlock, setConfirmUnlock] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [draft, setDraft] = useState<ManifestDraft>(draftOf(agent));
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setDraft(draftOf(agent)); setUnlocked(false); setConfirmUnlock(false); setConfirmDelete(false); } }, [open, agent]);

  const run = async (work: () => Promise<void>) => { setBusy(true); try { await work(); } catch (cause) { onToast((cause as Error).message); } finally { setBusy(false); } };
  const save = () => run(async () => { const next = await api.update(agent.id, manifestOf(draft)); onChanged(next); setUnlocked(false); onToast('已保存，下一个会话生效'); });
  const upgrade = () => run(async () => { const next = await api.upgrade(agent.id); onChanged(next); onToast(`已升级到 ${next.version || '最新版'}`); });
  const remove = () => run(async () => { await api.remove(agent.id); onOpenChange(false); onDeleted(); onToast('挂件已删除'); });

  return <Dialog open={open} onOpenChange={onOpenChange} label={`${agent.name} 设置`} className="w-[min(620px,94vw)]">
    <div className="flex max-h-[86vh] flex-col bg-[var(--overlay)]">
      <div className="flex items-center gap-2 px-5 pt-4 pb-3 shadow-[inset_0_-1px_0_var(--line)]">
        <h2 className="m-0 flex-1 text-[15px] font-semibold text-heading">{agent.name} · 设置</h2>
        <Button size="icon-sm" variant="ghost" aria-label="关闭" onClick={() => onOpenChange(false)}><X /></Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        <div className={cn('mb-4 flex items-start gap-2 rounded-xl px-3 py-2.5 text-[12.5px]', unlocked ? 'bg-brand-soft text-fg' : 'bg-sunken text-fg-2')}>
          {unlocked ? <LockOpen size={15} className="mt-0.5 shrink-0" /> : <Lock size={15} className="mt-0.5 shrink-0" />}
          <div className="flex-1">
            {unlocked ? '已解锁：改完点保存。' : '配置已锁定。Atlas 主体的任何改动、自动追新、自我进化都不会碰它；只有你在这里解锁才能改。'}
            {!unlocked && !confirmUnlock && <div className="mt-2"><Button size="sm" variant="secondary" onClick={() => setConfirmUnlock(true)}><LockOpen />解锁编辑</Button></div>}
            {confirmUnlock && !unlocked && <div className="mt-2 flex items-center gap-2"><span>确定要改「{agent.name}」的配置？</span>
              <Button size="sm" variant="primary" onClick={() => { setUnlocked(true); setConfirmUnlock(false); }}>确定解锁</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmUnlock(false)}>算了</Button></div>}
          </div>
        </div>
        <ManifestForm draft={draft} onChange={setDraft} disabled={!unlocked} />
        <dl className="mt-4 grid grid-cols-[88px_1fr] gap-x-2 gap-y-1 text-[12px] text-fg-3">
          <dt>来源</dt><dd className="m-0 text-fg-2">{agent.source}{agent.version ? ` · 版本 ${agent.version}（已钉死）` : ''}</dd>
          <dt>文件夹</dt><dd className="m-0 font-mono break-all text-fg-2 select-all">{agent.folder}</dd>
          <dt>工作目录</dt><dd className="m-0 font-mono break-all text-fg-2 select-all">{agent.workspace}</dd>
          {agent.repository && <><dt>主页</dt><dd className="m-0 break-all text-fg-2 select-all">{agent.repository}</dd></>}
        </dl>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3 shadow-[inset_0_1px_0_var(--line)]">
        {unlocked && agent.source.startsWith('registry:') && <Button size="sm" variant="secondary" disabled={busy} onClick={() => void upgrade()} title="换成注册表里的当前版本"><ArrowUpCircle />升级到最新版</Button>}
        {unlocked && !confirmDelete && <Button size="sm" variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)}><Trash2 />删除挂件</Button>}
        {confirmDelete && <><span className="text-[12.5px] text-danger">连同它的文件夹、会话记录一起删掉？</span>
          <Button size="sm" variant="danger" disabled={busy} onClick={() => void remove()}>确定删除</Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>算了</Button></>}
        <span className="flex-1" />
        <Button size="sm" variant="ghost" onClick={() => onOpenChange(false)}>关闭</Button>
        <Button size="sm" variant="primary" disabled={!unlocked || busy} onClick={() => void save()}>保存</Button>
      </div>
    </div>
  </Dialog>;
}
