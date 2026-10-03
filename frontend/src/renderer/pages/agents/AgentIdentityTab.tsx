import { useEffect, useState } from 'react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { field, fieldArea } from './shared';
import type { PersistentAgentRecord } from '../../services/persistentApi';

/** 身份·模型：常驻指令 / 模型 / 推理 / 工具白名单黑名单 / 工作目录 / 启用。 */
export default function AgentIdentityTab({ agent }: { agent: PersistentAgentRecord }) {
  const models = useAtlasStore((state) => state.models);
  const updateAgent = useAtlasStore((state) => state.updateAgent);
  const [form, setForm] = useState(() => ({
    description: agent.description ?? '',
    model: agent.model ?? '',
    reasoning: agent.reasoning_effort ?? '',
    instructions: agent.instructions ?? '',
    allow: (agent.tools?.allow ?? []).join(', '),
    deny: (agent.tools?.deny ?? []).join(', '),
    workspace: agent.agent?.workspace ?? '',
  }));
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  useEffect(() => setNote(''), [agent.id]);
  const dirty = form.description !== (agent.description ?? '')
    || form.model !== (agent.model ?? '')
    || form.reasoning !== (agent.reasoning_effort ?? '')
    || form.instructions !== (agent.instructions ?? '')
    || form.workspace !== (agent.agent?.workspace ?? '')
    || form.allow !== (agent.tools?.allow ?? []).join(', ')
    || form.deny !== (agent.tools?.deny ?? []).join(', ');

  const save = async () => {
    setBusy(true);
    const split = (value: string) => value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean);
    const result = await updateAgent(agent.id, {
      description: form.description.trim(),
      model: form.model,
      reasoning_effort: form.reasoning,
      instructions: form.instructions,
      tools: { allow: split(form.allow), deny: split(form.deny) },
      agent: { workspace: form.workspace.trim() },
    });
    setBusy(false);
    setNote(result ? '已保存' : '没有保存成功');
  };

  return <div className="grid max-w-[620px] gap-4">
    <label className="grid gap-1 text-[13px] text-fg-2">一句话职责
      <input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} className={field} />
    </label>
    <div className="grid grid-cols-2 gap-3">
      <label className="grid gap-1 text-[13px] text-fg-2">模型
        <select value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} className={field}>
          <option value="">跟随全局模型</option>
          {models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
        </select>
      </label>
      <label className="grid gap-1 text-[13px] text-fg-2">推理档位
        <select value={form.reasoning} onChange={(event) => setForm({ ...form, reasoning: event.target.value })} className={field}>
          <option value="">默认</option>
          {(['minimal', 'low', 'medium', 'high'] as const).map((effort) => <option key={effort} value={effort}>{effort}</option>)}
        </select>
      </label>
    </div>
    <label className="grid gap-1 text-[13px] text-fg-2">常驻指令
      <textarea rows={7} value={form.instructions} onChange={(event) => setForm({ ...form, instructions: event.target.value })}
        className={cn(fieldArea, 'resize-y leading-[1.65]')} />
    </label>
    <div className="grid grid-cols-2 gap-3">
      <label className="grid gap-1 text-[13px] text-fg-2">只许用的工具（逗号分隔，留空不限制）
        <input value={form.allow} onChange={(event) => setForm({ ...form, allow: event.target.value })} placeholder="read, write, browser" className={cn(field, 'font-mono text-[12.5px]')} />
      </label>
      <label className="grid gap-1 text-[13px] text-fg-2">禁用的工具
        <input value={form.deny} onChange={(event) => setForm({ ...form, deny: event.target.value })} placeholder="terminal" className={cn(field, 'font-mono text-[12.5px]')} />
      </label>
    </div>
    <label className="grid gap-1 text-[13px] text-fg-2">工作目录（留空跟随主工作区）
      <input value={form.workspace} onChange={(event) => setForm({ ...form, workspace: event.target.value })} className={cn(field, 'font-mono text-[12.5px]')} />
    </label>
    <div className="flex items-center gap-3">
      <Button variant="primary" disabled={!dirty || busy} onClick={() => void save()}>{busy ? '保存中…' : '保存'}</Button>
      {note && <span role="status" className="text-[12.5px] text-fg-3">{note}</span>}
    </div>
  </div>;
}
