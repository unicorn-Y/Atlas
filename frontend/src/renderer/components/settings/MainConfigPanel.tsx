import { useEffect, useMemo, useRef, useState } from 'react';
import { FileCog, History, RotateCcw, Save, SlidersHorizontal, Undo2, Zap } from 'lucide-react';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

interface ConfigState {
  config_path: string; config_text: string; settings_path: string; settings_text: string;
  effective_text: string; expert_enabled: boolean;
  backups: Array<{ name: string; kind: 'config' | 'settings'; size: number }>;
}
type Tab = 'config' | 'settings' | 'effective' | 'backups';

async function call<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

/** 带行号的等宽编辑区；Ctrl+S 保存。 */
function CodeEditor({ value, onChange, readOnly, onSave }: { value: string; onChange?: (value: string) => void; readOnly?: boolean; onSave?: () => void }) {
  const gutterRef = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => Math.max(1, value.split('\n').length), [value]);
  return <div className="flex h-[min(58vh,560px)] overflow-hidden rounded-xl bg-code shadow-[inset_0_0_0_1px_var(--line)] focus-within:shadow-[inset_0_0_0_1px_var(--brand)]">
    <div ref={gutterRef} aria-hidden className="w-11 shrink-0 overflow-hidden py-2.5 pr-2 text-right font-mono text-[12px] leading-[1.6] text-fg-3/70 select-none shadow-[inset_-1px_0_0_var(--line)]">
      {Array.from({ length: lines }, (_, index) => <div key={index}>{index + 1}</div>)}
    </div>
    <textarea value={value} readOnly={readOnly} spellCheck={false} wrap="off"
      onChange={(event) => onChange?.(event.target.value)}
      onScroll={(event) => { if (gutterRef.current) gutterRef.current.scrollTop = event.currentTarget.scrollTop; }}
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); onSave?.(); }
        else if (event.key === 'Tab' && !readOnly) {
          event.preventDefault();
          const el = event.currentTarget; const start = el.selectionStart; const end = el.selectionEnd;
          onChange?.(`${value.slice(0, start)}  ${value.slice(end)}`);
          requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + 2; });
        }
      }}
      className={cn('min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 font-mono text-[12.5px] leading-[1.6] text-fg outline-none', readOnly && 'text-fg-2')} />
  </div>;
}

/** 设置 → 主体配置：atlas.toml、界面设置、当前生效的配置和自动备份。 */
export default function MainConfigPanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const [state, setState] = useState<ConfigState | null>(null);
  const [tab, setTab] = useState<Tab>('config');
  const [configText, setConfigText] = useState('');
  const [settingsText, setSettingsText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const apply = (next: ConfigState) => { setState(next); setConfigText(next.config_text); setSettingsText(next.settings_text); setError(''); };
  useEffect(() => { void call<ConfigState>(apiBaseUrl, '/api/config/main').then(apply).catch((cause: Error) => setError(cause.message)); }, [apiBaseUrl]);

  const run = async (work: () => Promise<ConfigState>, done: string) => {
    setBusy(true);
    try { apply(await work()); onToast(done); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  const saveConfig = () => run(() => call(apiBaseUrl, '/api/config/main', { method: 'PUT', body: JSON.stringify({ text: configText }) }), '主体配置已保存');
  const saveSettings = () => run(() => call(apiBaseUrl, '/api/config/settings', { method: 'PUT', body: JSON.stringify({ text: settingsText }) }), '界面设置已保存');
  const restore = (name: string) => run(() => call(apiBaseUrl, '/api/config/restore', { method: 'POST', body: JSON.stringify({ name }) }), '已恢复到这个备份');

  if (!state) return error ? <p className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p> : <p className="m-0 text-[13px] text-fg-3">加载中…</p>;

  const configDirty = configText !== state.config_text;
  const settingsDirty = settingsText !== state.settings_text;
  const tabs: Array<[Tab, string, typeof FileCog, boolean]> = [
    ['config', '主配置', FileCog, configDirty], ['settings', '界面设置', SlidersHorizontal, settingsDirty],
    ['effective', '当前生效', Zap, false], ['backups', '备份', History, false],
  ];
  const stamp = (name: string) => { const m = name.match(/bak-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/); return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : name; };

  return <div className="grid gap-3">
    <div role="tablist" className="flex w-fit gap-0.5 rounded-[10px] bg-sunken p-[3px] shadow-[inset_0_0_0_1px_var(--line)]">
      {tabs.map(([id, label, Icon, dirty]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
        className={cn('inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12.5px] transition-colors', tab === id ? 'raised text-fg' : 'text-fg-2 hover:text-fg')}>
        <Icon size={13} />{label}{dirty && <span className="size-1.5 rounded-full bg-brand" title="有未保存的修改" />}
      </button>)}
    </div>

    {error && <p className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] whitespace-pre-wrap text-danger">{error}</p>}

    {tab === 'config' && <>
      <p className="m-0 text-[12px] text-fg-3">Atlas 主体的 <code>atlas.toml</code>。保存前会检查写法，旧版本自动备份；大部分设置下一轮对话生效，模型网关、工具服务器等启动项重启 Atlas 后生效。<span className="font-mono select-all"> {state.config_path}</span></p>
      <CodeEditor value={configText} onChange={setConfigText} onSave={() => { if (configDirty) void saveConfig(); }} />
      <div className="flex items-center justify-end gap-2">
        {configDirty && <Button size="sm" variant="ghost" onClick={() => setConfigText(state.config_text)}><Undo2 />撤销修改</Button>}
        <Button size="sm" variant="primary" disabled={!configDirty || busy} onClick={() => void saveConfig()}><Save />保存<kbd className="ml-1 text-[10.5px] opacity-70">Ctrl S</kbd></Button>
      </div>
    </>}

    {tab === 'settings' && <>
      <p className="m-0 text-[12px] text-fg-3">你在界面里改过的设置（模型、密钥、偏好等），优先级高于 atlas.toml。里面有密钥，别截图外传。<span className="font-mono select-all"> {state.settings_path}</span></p>
      <CodeEditor value={settingsText} onChange={setSettingsText} onSave={() => { if (settingsDirty) void saveSettings(); }} />
      <div className="flex items-center justify-end gap-2">
        {settingsDirty && <Button size="sm" variant="ghost" onClick={() => setSettingsText(state.settings_text)}><Undo2 />撤销修改</Button>}
        <Button size="sm" variant="primary" disabled={!settingsDirty || busy} onClick={() => void saveSettings()}><Save />保存<kbd className="ml-1 text-[10.5px] opacity-70">Ctrl S</kbd></Button>
      </div>
    </>}

    {tab === 'effective' && <>
      <p className="m-0 flex items-center gap-1.5 text-[12px] text-fg-3">
        {state.expert_enabled ? <><Zap size={12} className="fill-current text-brand" />专家模式开着：这里是 atlas.toml 叠上专家配置之后、Atlas 实际在用的结果。</> : '普通模式：Atlas 实际在用的就是 atlas.toml。'}只读。
      </p>
      <CodeEditor value={state.effective_text} readOnly />
    </>}

    {tab === 'backups' && <div className="grid gap-1.5">
      <p className="m-0 text-[12px] text-fg-3">每次保存前自动留一份，各保留最近 30 份。恢复也会先把当前版本备份。</p>
      {!state.backups.length && <p className="m-0 rounded-xl bg-sunken px-3 py-4 text-center text-[12.5px] text-fg-3">还没有备份，保存一次后会出现在这里。</p>}
      {state.backups.map((item) => <div key={item.name} className="flex items-center gap-3 rounded-xl card-surface px-3 py-2 text-[12.5px]">
        <span className={cn('rounded-md px-1.5 py-0.5 text-[11px]', item.kind === 'config' ? 'bg-brand-soft text-brand' : 'bg-sunken text-fg-2')}>{item.kind === 'config' ? '主配置' : '界面设置'}</span>
        <span className="flex-1 text-fg">{stamp(item.name)}</span>
        <span className="text-[11.5px] text-fg-3">{(item.size / 1024).toFixed(1)} KB</span>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void restore(item.name)}><RotateCcw />恢复</Button>
      </div>)}
    </div>}
  </div>;
}
