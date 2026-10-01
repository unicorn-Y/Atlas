import { useEffect, useState, type ReactNode } from 'react';
import { AlertTriangle, Check, ChevronRight, FileText } from 'lucide-react';
import type { AgentTypeInfo, ModelInfo, OrchestrationSettings } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { cn } from '../ui/cn';

const AGENT_LABEL: Record<string, string> = { explore: '探索', researcher: '调研', plan: '规划', oracle: '深度分析', verifier: '验收', general: '通用' };
const SOURCE: Record<string, string> = { builtin: '内置', user: '我的', workspace: '项目', claude: 'Claude Code', opencode: 'OpenCode', codex: 'Codex', copilot: 'Copilot' };
const MODEL_HINT: Record<string, string> = { inherit: '跟主任务一样', fast: '快模型', strong: '强模型' };
const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

/** Sub-agents: which models they use, how many run at once, consultation models, and the available types. */
export default function SubAgentsPanel({ models, workspace }: { models: ModelInfo[]; workspace: string }) {
  const [settings, setSettings] = useState<OrchestrationSettings | null>(null);
  const [types, setTypes] = useState<AgentTypeInfo[] | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    backend.getAgentSettings().then(setSettings).catch((exc) => setStatus({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }));
    backend.getAgentTypes(workspace || null).then(setTypes).catch(() => setTypes([]));
  }, [workspace]);

  const save = async (patch: Partial<OrchestrationSettings>) => {
    if (!settings) return;
    setSettings({ ...settings, ...patch });
    try { setSettings(await backend.saveAgentSettings(patch)); setStatus({ ok: true, text: '已保存' }); }
    catch (exc) { setStatus({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); backend.getAgentSettings().then(setSettings).catch(() => {}); }
  };
  const modelName = (id: string) => models.find((model) => model.id === id)?.name ?? id;

  if (!settings) return <p className="text-[13px] text-fg-3">{status?.text ?? '正在读取…'}</p>;
  const references = settings.moa_reference_models;
  return <div className="grid gap-6 text-[13px]">
    <Block title="子 Agent 用的模型" hint="类型里写着「快模型」的（比如探索）用前者，写着「强模型」的（比如深度分析）用后者；不选就跟主任务用同一个。">
      <div className="grid grid-cols-2 gap-3">
        {([['fast_model', '快模型'], ['strong_model', '强模型']] as const).map(([key, label]) => <label key={key} className="grid gap-1 text-fg-2">{label}
          <select value={settings[key]} onChange={(event) => void save({ [key]: event.target.value })} className={field}>
            <option value="">跟主任务一样</option>
            {models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
          </select>
        </label>)}
      </div>
    </Block>

    <Block title="委派" hint="一次并行派多少个子 Agent，以及子 Agent 能不能继续往下派。">
      <div className="grid gap-3">
        <Steps label="同时最多" unit="个" values={[1, 2, 3, 4]} value={settings.max_concurrent_children} onChange={(value) => void save({ max_concurrent_children: value })} />
        <Steps label="最多嵌套" unit="层" values={[1, 2, 3]} value={settings.max_spawn_depth} onChange={(value) => void save({ max_spawn_depth: value })}
          note={settings.max_spawn_depth === 1 ? '子 Agent 不能再派子 Agent' : `协调者可以再派 ${settings.max_spawn_depth - 1} 层`} />
      </div>
    </Block>

    <Block title="多模型会诊" hint="在输入框「运行方式」里打开会诊，或者消息前面加 /moa：Atlas 回答前会先听这些模型的意见。">
      <div className="flex flex-wrap gap-1.5">
        {models.map((model) => {
          const on = references.includes(model.id);
          const full = !on && references.length >= 8;
          return <button key={model.id} disabled={full} aria-pressed={on}
            onClick={() => void save({ moa_reference_models: on ? references.filter((id) => id !== model.id) : [...references, model.id] })}
            className={cn('inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[12.5px] disabled:opacity-40', on ? 'bg-brand-soft text-fg' : 'bg-sunken text-fg-2 hover:text-fg')}>
            {on && <Check size={12} />}{model.name || model.id}</button>;
        })}
      </div>
      {references.length > 0 && <Steps label="每次最多参考" unit="个" values={[1, 2, 3, 4, 5, 6, 7, 8].filter((value) => value <= Math.max(references.length, 1))}
        value={Math.min(settings.moa_max_references, references.length)} onChange={(value) => void save({ moa_max_references: value })} />}
      {!references.length && <p className="m-0 text-[12.5px] text-fg-3">还没选参考模型，会诊用不了。</p>}
    </Block>

    <Block title="子 Agent 类型" hint="Atlas 委派任务时从这里选。项目里 .atlas/agents、.claude/agents 等目录下的定义也会列出来，项目目录要先信任。">
      {types === null && <p className="m-0 text-fg-3">正在读取…</p>}
      <ul className="m-0 grid list-none gap-1 p-0">
        {types?.map((type) => {
          const expanded = open === type.name;
          const tools = Array.isArray(type.tools) ? type.tools : type.tools ? String(type.tools).split(',').map((item) => item.trim()) : [];
          return <li key={`${type.source}:${type.name}`} className="rounded-xl bg-sunken">
            <button onClick={() => setOpen(expanded ? null : type.name)} aria-expanded={expanded} className="flex w-full items-center gap-2 px-3 py-2 text-left">
              <ChevronRight size={13} className={cn('shrink-0 text-fg-3 transition-transform', expanded && 'rotate-90')} />
              <b className="shrink-0 font-medium text-fg">{AGENT_LABEL[type.name] ?? type.name}</b>
              {AGENT_LABEL[type.name] && <code className="shrink-0 font-mono text-[11.5px] text-fg-3">{type.name}</code>}
              <span className="min-w-0 flex-1 truncate text-[12px] text-fg-3">{type.description}</span>
              {type.warnings.length > 0 && <AlertTriangle size={13} className="shrink-0 text-brand" aria-label={`${type.warnings.length} 条警告`} />}
              {!type.trusted && <span className="shrink-0 rounded-full bg-hover px-1.5 text-[11px] text-fg-3">未信任</span>}
              <span className="shrink-0 rounded-full bg-overlay px-1.5 text-[11px] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">{SOURCE[type.source] ?? type.source}</span>
            </button>
            {expanded && <div className="anim-fade grid gap-1.5 px-3 pb-3 pl-[33px] text-[12.5px] text-fg-2">
              <p className="m-0 leading-[1.65]">{type.description}</p>
              <p className="m-0 text-fg-3">模型：<span className="text-fg-2">{type.model ? MODEL_HINT[type.model] ?? modelName(type.model) : '跟主任务一样'}</span>
                <span className="mx-2">·</span>角色：<span className="text-fg-2">{type.role === 'orchestrator' ? '协调者（可以再派子 Agent）' : '执行者'}</span></p>
              <p className="m-0 text-fg-3">工具：<span className="text-fg-2">{tools.length ? tools.join('、') : '全部（受主任务权限约束）'}</span></p>
              {type.path && <p className="m-0 flex items-center gap-1 font-mono text-[11.5px] text-fg-3"><FileText size={12} />{type.path}</p>}
              {type.warnings.map((warning) => <p key={warning} className="m-0 rounded-lg bg-brand-soft px-2.5 py-1 text-fg">{warning}</p>)}
            </div>}
          </li>;
        })}
      </ul>
    </Block>
    {status && <p role="status" className={cn('m-0 text-[12.5px]', status.ok ? 'text-ok' : 'text-danger')}>{status.text}</p>}
  </div>;
}

function Block({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return <section className="grid gap-2.5">
    <div><h4 className="m-0 text-[14px] font-semibold text-heading">{title}</h4><p className="m-0 mt-0.5 text-[12.5px] leading-[1.6] text-fg-3">{hint}</p></div>
    {children}
  </section>;
}

function Steps({ label, unit, values, value, onChange, note }: { label: string; unit: string; values: number[]; value: number; onChange: (value: number) => void; note?: string }) {
  return <div className="flex flex-wrap items-center gap-3">
    <span className="w-24 text-fg-2">{label}</span>
    <div className="flex rounded-[9px] bg-sunken p-0.5" role="radiogroup" aria-label={label}>
      {values.map((item) => <button key={item} role="radio" aria-checked={item === value} onClick={() => onChange(item)}
        className={cn('h-7 min-w-9 rounded-[7px] px-2 text-[12.5px] tabular-nums', item === value ? 'bg-overlay text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}>{item}</button>)}
    </div>
    <span className="text-fg-3">{unit}{note ? ` · ${note}` : ''}</span>
  </div>;
}
