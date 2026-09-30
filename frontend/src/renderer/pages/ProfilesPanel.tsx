import { useEffect, useState, type FormEvent } from 'react';
import { Plus, Trash2, UserCog } from 'lucide-react';
import type { AgentProfile, ModelInfo, SkillInfo } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

const BUILT_IN = new Set(['default', 'architect', 'reviewer']);
const EFFORTS = [['', '跟随模型'], ['minimal', '最低'], ['low', '低'], ['medium', '中'], ['high', '高']] as const;
const splitList = (value: string) => value.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean);

interface Draft { id?: string; name: string; description: string; instructions: string; model: string; reasoning_effort: string; mode: 'act' | 'plan'; active_skills: string[]; allow: string; deny: string; limitTools: boolean }

const toDraft = (profile?: AgentProfile): Draft => ({
  id: profile?.id, name: profile?.name ?? '', description: profile?.description ?? '', instructions: profile?.instructions ?? '',
  model: profile?.model ?? '', reasoning_effort: profile?.reasoning_effort ?? '', mode: profile?.mode ?? 'act', active_skills: profile?.active_skills ?? [],
  allow: (profile?.tools?.allow ?? []).join(', '), deny: (profile?.tools?.deny ?? []).join(', '), limitTools: Boolean(profile?.tools?.allow),
});

/** Roles bundle instructions, model, skills, tools and mode; pick one in the composer. */
export default function ProfilesPanel({ profiles, models, skills, onChanged }: {
  profiles: AgentProfile[]; models: ModelInfo[]; skills: SkillInfo[]; onChanged: () => void;
}) {
  const [selected, setSelected] = useState<string>(profiles[0]?.id ?? '');
  const [draft, setDraft] = useState<Draft>(toDraft(profiles[0]));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  useEffect(() => { if (selected !== 'new') setDraft(toDraft(profiles.find((profile) => profile.id === selected))); setConfirmDelete(false); setMessage(''); }, [selected, profiles]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setMessage('');
    try {
      const saved = await backend.saveProfile({
        ...(draft.id ? { id: draft.id } : {}), name: draft.name.trim(), description: draft.description, instructions: draft.instructions,
        model: draft.model || null, reasoning_effort: (draft.reasoning_effort || null) as AgentProfile['reasoning_effort'], mode: draft.mode, active_skills: draft.active_skills,
        tools: { allow: draft.limitTools ? splitList(draft.allow) : null, deny: splitList(draft.deny) },
      });
      setSelected(saved.id);
      setMessage('已保存');
      onChanged();
    } catch (exc) { setMessage(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!draft.id) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    setBusy(true);
    try { await backend.deleteProfile(draft.id); setSelected(profiles.find((profile) => profile.id !== draft.id)?.id ?? ''); onChanged(); }
    catch (exc) { setMessage(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); setConfirmDelete(false); }
  };

  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <div className="grid grid-cols-[170px_minmax(0,1fr)] gap-5">
    <nav className="grid content-start gap-1" aria-label="角色列表">
      {profiles.map((profile) => <button key={profile.id} onClick={() => setSelected(profile.id)} aria-current={selected === profile.id}
        className={cn('flex items-center gap-2 truncate rounded-lg px-2.5 py-2 text-left text-[13px]', selected === profile.id ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
        <UserCog size={14} className="shrink-0" /><span className="truncate">{profile.name}</span>
      </button>)}
      <button onClick={() => { setSelected('new'); setDraft(toDraft()); }} className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', selected === 'new' ? 'bg-selected text-fg' : 'text-brand hover:bg-hover')}><Plus size={14} />新建角色</button>
    </nav>
    <form onSubmit={(event) => void save(event)} className="grid content-start gap-3.5 text-[13px] text-fg-2">
      <label className="grid gap-1">名称<input required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className={field} placeholder="比如：前端工程师" /></label>
      <label className="grid gap-1">一句话说明<input value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} className={field} placeholder="在角色菜单里显示" /></label>
      <label className="grid gap-1">额外指令<textarea value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} rows={4}
        className={cn(field, 'h-auto py-2 leading-[1.6]')} placeholder="追加到系统提示，比如「回答前先列出要改的文件」" /></label>
      <div className="grid grid-cols-3 gap-3">
        <label className="grid gap-1">模型<select value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} className={field}>
          <option value="">跟随当前选择</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name ?? model.id}</option>)}</select></label>
        <label className="grid gap-1">推理档位<select value={draft.reasoning_effort} onChange={(event) => setDraft({ ...draft, reasoning_effort: event.target.value })} className={field}>
          {EFFORTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="grid gap-1">模式<select value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value as 'act' | 'plan' })} className={field}>
          <option value="act">直接执行</option><option value="plan">先出计划</option></select></label>
      </div>
      {skills.length > 0 && <fieldset className="grid gap-1.5"><legend className="mb-1">默认启用的技能</legend>
        <div className="flex flex-wrap gap-1.5">{skills.map((skill) => {
          const on = draft.active_skills.includes(skill.name);
          return <button type="button" key={skill.name} aria-pressed={on} title={skill.description} onClick={() => setDraft({ ...draft, active_skills: on ? draft.active_skills.filter((name) => name !== skill.name) : [...draft.active_skills, skill.name] })}
            className={cn('rounded-lg px-2 py-1 text-[12.5px]', on ? 'bg-brand-soft text-fg' : 'bg-sunken text-fg-3 hover:text-fg')}>{skill.name}</button>;
        })}</div></fieldset>}
      <fieldset className="grid gap-2"><legend className="mb-1">工具</legend>
        <label className="flex items-center gap-2"><input type="checkbox" checked={draft.limitTools} onChange={(event) => setDraft({ ...draft, limitTools: event.target.checked })} />只允许下面这些工具</label>
        {draft.limitTools && <input value={draft.allow} onChange={(event) => setDraft({ ...draft, allow: event.target.value })} className={field} placeholder="local_file, coding.repo_map" />}
        <label className="grid gap-1">禁止的工具<input value={draft.deny} onChange={(event) => setDraft({ ...draft, deny: event.target.value })} className={field} placeholder="local_shell, computer_mouse" /></label>
      </fieldset>
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={busy || !draft.name.trim()}>{draft.id ? '保存' : '创建角色'}</Button>
        {draft.id && !BUILT_IN.has(draft.id) && <Button variant={confirmDelete ? 'danger' : 'ghost'} disabled={busy} onClick={() => void remove()}><Trash2 />{confirmDelete ? '确认删除' : '删除'}</Button>}
        {draft.id && BUILT_IN.has(draft.id) && <span className="text-[12px] text-fg-3">内置角色可以改，不能删</span>}
        {message && <span role="status" className={cn('text-[12.5px]', message === '已保存' ? 'text-ok' : 'text-danger')}>{message}</span>}
      </div>
    </form>
  </div>;
}
