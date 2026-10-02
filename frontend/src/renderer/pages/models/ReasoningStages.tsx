import type { ReasoningEffort, ReasoningStagesConfig } from '@atlas/backend-adapter';

interface ReasoningStagesProps {
  config: ReasoningStagesConfig;
  busy?: boolean;
  /** Called for every change; the parent decides when to persist. */
  onChange: (config: ReasoningStagesConfig) => void;
}

const EFFORTS: Array<[ReasoningEffort, string]> = [['minimal', '最低'], ['low', '低'], ['medium', '中'], ['high', '高']];

type Stage = Exclude<keyof ReasoningStagesConfig, 'enabled'>;
const STAGES: Array<[Stage, string, string]> = [
  ['planning', '规划档', '首轮对话和计划模式下用：想清楚要做什么'],
  ['execution', '执行档', '正常干活时用：执行工具、写代码'],
  ['verification', '验收档', '完成前自检时用：核对结果有没有做对'],
];

/** Split the thinking budget per run phase; off = one effort for everything (the old behaviour). */
export default function ReasoningStages({ config, busy, onChange }: ReasoningStagesProps) {
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <div className="grid gap-3 text-[13px] text-fg-2">
    <label className="flex items-start gap-2.5">
      <input type="checkbox" className="mt-1" checked={config.enabled} disabled={busy}
        onChange={(event) => onChange({ ...config, enabled: event.target.checked })} />
      <span>
        <span className="block font-medium text-fg">开启分阶段思考量</span>
        <small className="mt-0.5 block text-[12px] leading-[1.6] text-fg-3">关闭时和以前一样：整个任务共用一个推理档位。开启后，不同阶段可以给不同的思考量，省钱又稳。</small>
      </span>
    </label>
    {config.enabled && <div className="grid gap-3 rounded-xl bg-sunken px-3.5 py-3 sm:grid-cols-3">
      {STAGES.map(([stage, label, hint]) => <label key={stage} className="grid content-start gap-1">
        <span className="text-[12.5px] font-medium text-fg-2">{label}</span>
        <select value={config[stage]} disabled={busy} className={field}
          onChange={(event) => onChange({ ...config, [stage]: event.target.value as ReasoningEffort })}>
          {EFFORTS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select>
        <small className="text-[11.5px] leading-[1.55] text-fg-3">{hint}</small>
      </label>)}
    </div>}
  </div>;
}
