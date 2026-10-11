import { useEffect, useState, type FormEvent } from 'react';
import { MessageSquareText, Save } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

type OutputStylePreset = 'concise' | 'balanced' | 'detailed' | 'custom';

type OutputStyleSettings = {
  preset: OutputStylePreset;
  custom_persona: string;
  max_custom_persona_chars: number;
  applies_to: 'new_runs';
};

const PRESETS: Array<{ id: OutputStylePreset; label: string; description: string }> = [
  { id: 'concise', label: '简洁', description: '先给结果，压缩非必要解释。' },
  { id: 'balanced', label: '均衡', description: '根据任务需要提供适量背景和步骤。' },
  { id: 'detailed', label: '详细', description: '在复杂任务中说明依据、步骤和取舍。' },
  { id: 'custom', label: '自定义 persona', description: '补充你偏好的表达语气和呈现方式。' },
];

export default function OutputStyleSettingsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [settings, setSettings] = useState<OutputStyleSettings | null>(null);
  const [preset, setPreset] = useState<OutputStylePreset>('balanced');
  const [customPersona, setCustomPersona] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api<OutputStyleSettings>(apiBaseUrl, '/api/settings/output-style');
      setSettings(result);
      setPreset(result.preset);
      setCustomPersona(result.custom_persona);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [apiBaseUrl]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!settings || saving) return;
    if (preset === 'custom' && !customPersona.trim()) {
      setError('请填写自定义 persona 描述。');
      setMessage(null);
      return;
    }

    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await api<OutputStyleSettings>(apiBaseUrl, '/api/settings/output-style', {
        method: 'PUT',
        json: { preset, custom_persona: customPersona },
      });
      setSettings(updated);
      setPreset(updated.preset);
      setCustomPersona(updated.custom_persona);
      setMessage('已保存，新启动的运行会采用此表达偏好。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  const maxChars = settings?.max_custom_persona_chars ?? 2000;

  return <section className="grid max-w-[760px] gap-4 text-[12.5px] text-fg-2" aria-labelledby="output-style-title">
    <header className="grid gap-1">
      <h2 id="output-style-title" className="m-0 flex items-center gap-2 text-[15px] font-semibold text-fg"><MessageSquareText size={17} /> 输出风格</h2>
      <p className="m-0 text-[12px] text-fg-3">此用户级偏好用于新运行的表达方式；当前请求、工作区规则和 profile 指令仍然生效。</p>
    </header>

    {loading && <p role="status" className="m-0 text-fg-3">正在读取输出风格设置…</p>}
    {!loading && error && !settings && <div className="grid gap-2 rounded-xl bg-danger-soft p-3 text-danger" role="alert">
      <p className="m-0">无法读取输出风格设置：{error}</p>
      <div><Button type="button" size="sm" onClick={() => void load()}>重试</Button></div>
    </div>}

    {settings && <form onSubmit={(event) => void save(event)} className="grid gap-4">
      <fieldset className="grid gap-2 border-0 p-0 m-0" disabled={loading || saving}>
        <legend className="mb-2 font-medium text-fg">选择风格</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {PRESETS.map((option) => <label key={option.id} className={cn(
            'grid cursor-pointer gap-1 rounded-xl p-3 shadow-[inset_0_0_0_1px_var(--line)] transition-colors',
            preset === option.id ? 'bg-brand-soft shadow-[inset_0_0_0_1.5px_var(--brand)]' : 'bg-sunken hover:bg-hover',
          )}>
            <span className="flex items-center gap-2 font-medium text-fg">
              <input type="radio" name="output-style-preset" value={option.id} checked={preset === option.id} onChange={() => { setPreset(option.id); setError(null); setMessage(null); }} />
              {option.label}
            </span>
            <span className="pl-6 text-[12px] leading-relaxed text-fg-3">{option.description}</span>
          </label>)}
        </div>
      </fieldset>

      {preset === 'custom' && <label className="grid gap-1.5">
        <span className="font-medium text-fg">Persona 描述</span>
        <textarea
          value={customPersona}
          onChange={(event) => { setCustomPersona(event.target.value); setError(null); setMessage(null); }}
          maxLength={maxChars}
          rows={5}
          placeholder="例如：语气自然友好，先概述结论，再用短段落解释关键点。"
          className="min-h-28 resize-y rounded-[9px] bg-sunken px-3 py-2 text-[13px] leading-relaxed text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-60"
          disabled={saving}
        />
        <span className="text-right text-[11.5px] text-fg-3">{customPersona.length} / {maxChars}</span>
      </label>}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={loading || saving}>
          <Save />{saving ? '保存中…' : '保存输出风格'}
        </Button>
        {message && <span role="status" className="text-[12px] text-brand">{message}</span>}
      </div>
    </form>}

    {error && settings && <p role="alert" className="m-0 whitespace-pre-wrap text-[12px] text-danger">{error}</p>}
  </section>;
}
