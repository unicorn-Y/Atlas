import { useEffect, useState } from 'react';
import { Zap } from 'lucide-react';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

interface ExpertStatus {
  enabled: boolean; config_path: string; instructions_path: string;
  config_text: string; instructions_text: string; overlay_sections: string[]; config_error: string;
}

const EVENT = 'atlas:expert-mode';

async function call<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

const area = 'w-full rounded-lg bg-sunken px-2.5 py-2 font-mono text-[12.5px] leading-[1.55] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

/** 设置 → 专家模式：开关，以及开着时额外加载的配置覆盖层和附加说明。 */
export default function ExpertModePanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const [status, setStatus] = useState<ExpertStatus | null>(null);
  const [configText, setConfigText] = useState('');
  const [instructionsText, setInstructionsText] = useState('');
  const [busy, setBusy] = useState(false);

  const apply = (next: ExpertStatus) => {
    setStatus(next); setConfigText(next.config_text); setInstructionsText(next.instructions_text);
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next.enabled }));
  };
  useEffect(() => { void call<ExpertStatus>(apiBaseUrl, '/api/expert-mode').then(apply).catch((cause: Error) => onToast(cause.message)); }, [apiBaseUrl]);

  const run = async (work: () => Promise<ExpertStatus>, done: string) => {
    setBusy(true);
    try { apply(await work()); onToast(done); } catch (cause) { onToast((cause as Error).message); } finally { setBusy(false); }
  };
  const toggle = () => run(() => call(apiBaseUrl, '/api/expert-mode/toggle', { method: 'POST', body: JSON.stringify({ enabled: !status?.enabled }) }),
    status?.enabled ? '已切回普通模式' : '已切到专家模式');
  const save = () => run(() => call(apiBaseUrl, '/api/expert-mode', { method: 'PUT', body: JSON.stringify({ config_text: configText, instructions_text: instructionsText }) }), '已保存');
  const dirty = !!status && (configText !== status.config_text || instructionsText !== status.instructions_text);

  if (!status) return <p className="m-0 text-[13px] text-fg-3">加载中…</p>;
  return <div className="grid gap-5">
    <div className={cn('flex items-center gap-3 rounded-xl px-4 py-3', status.enabled ? 'bg-brand-soft' : 'bg-sunken')}>
      <Zap size={18} className={status.enabled ? 'text-brand' : 'text-fg-3'} />
      <div className="flex-1 text-[13px]">
        <p className="m-0 font-semibold text-fg">{status.enabled ? '专家模式已开启' : '现在是普通模式'}</p>
        <p className="m-0 text-[12px] text-fg-3">开启后，在普通配置之上额外加载下面两份内容；关掉后普通配置原样不动。</p>
      </div>
      <Button variant={status.enabled ? 'secondary' : 'primary'} disabled={busy} onClick={() => void toggle()}>{status.enabled ? '切回普通模式' : '切到专家模式'}</Button>
    </div>

    <label className="grid gap-1.5 text-[12.5px] text-fg-2">
      <span className="font-semibold text-fg">额外配置（覆盖层）</span>
      <span className="text-[12px] text-fg-3">和 atlas.toml 一样的写法，只写要改的部分，按小节深度合并到普通配置上。模型网关、工具服务器等启动时读取的项要重启 Atlas 才生效；其余从下一轮对话起生效。</span>
      <textarea className={area} rows={10} spellCheck={false} value={configText} onChange={(event) => setConfigText(event.target.value)}
        placeholder={'# 例如\n[models]\ndefault = "某个模型"\n\n[agent]\n...'} />
      {status.config_error && <span className="text-[12px] text-danger">现有文件写法有错，没有生效：{status.config_error}</span>}
      {!!status.overlay_sections.length && <span className="text-[12px] text-fg-3">会覆盖的小节：{status.overlay_sections.join('、')}</span>}
      <span className="font-mono text-[11.5px] text-fg-3 select-all">{status.config_path}</span>
    </label>

    <label className="grid gap-1.5 text-[12.5px] text-fg-2">
      <span className="font-semibold text-fg">附加说明</span>
      <span className="text-[12px] text-fg-3">专家模式下每轮拼到系统提示词末尾。</span>
      <textarea className={area} rows={8} spellCheck={false} value={instructionsText} onChange={(event) => setInstructionsText(event.target.value)} />
      <span className="font-mono text-[11.5px] text-fg-3 select-all">{status.instructions_path}</span>
    </label>

    <div className="flex justify-end gap-2">
      {dirty && <Button variant="ghost" onClick={() => { setConfigText(status.config_text); setInstructionsText(status.instructions_text); }}>撤销修改</Button>}
      <Button variant="primary" disabled={!dirty || busy} onClick={() => void save()}>保存</Button>
    </div>
  </div>;
}

/** 专家模式开着、又不在聊天界面时，窗口右上角挂着的提醒。 */
export function ExpertModeBadge({ apiBaseUrl, onOpen }: { apiBaseUrl: string; onOpen: () => void }) {
  const [enabled] = useExpertMode(apiBaseUrl);
  if (!enabled) return null;
  return <button onClick={onOpen} title="专家模式已开启，点这里查看或关闭"
    className="fixed top-2 right-36 z-40 inline-flex items-center gap-1 rounded-full bg-brand px-2.5 py-0.5 text-[11.5px] font-semibold text-white shadow-md [-webkit-app-region:no-drag]">
    <Zap size={12} className="fill-current" />专家模式
  </button>;
}

/** 专家模式当前是否开启；各处的开关、角标共用同一个事件保持同步。 */
export function useExpertMode(apiBaseUrl: string): [boolean, (enabled: boolean) => Promise<void>] {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    void call<ExpertStatus>(apiBaseUrl, '/api/expert-mode').then((s) => setEnabled(s.enabled)).catch(() => undefined);
    const listener = (event: Event) => setEnabled(Boolean((event as CustomEvent<boolean>).detail));
    window.addEventListener(EVENT, listener);
    return () => window.removeEventListener(EVENT, listener);
  }, [apiBaseUrl]);
  const toggle = async (next: boolean) => {
    const status = await call<ExpertStatus>(apiBaseUrl, '/api/expert-mode/toggle', { method: 'POST', body: JSON.stringify({ enabled: next }) });
    window.dispatchEvent(new CustomEvent(EVENT, { detail: status.enabled }));
  };
  return [enabled, toggle];
}

/** 打开设置里的专家模式页（App 监听）。 */
export const OPEN_EXPERT_SETTINGS = 'atlas:open-expert-settings';

/** 输入框工具栏上的专家模式开关：点一下切换，右键打开设置。 */
export function ExpertModeToggle({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [enabled, toggle] = useExpertMode(apiBaseUrl);
  const [busy, setBusy] = useState(false);
  const flip = async () => { setBusy(true); try { await toggle(!enabled); } catch { /* backend offline: state unchanged */ } finally { setBusy(false); } };
  return <button type="button" role="switch" aria-checked={enabled} aria-label={enabled ? '关闭专家模式' : '开启专家模式'} disabled={busy}
    title={enabled ? '专家模式已开启：点击切回普通模式，右键编辑专家配置' : '切到专家模式（右键编辑专家配置）'}
    onClick={() => void flip()}
    onContextMenu={(event) => { event.preventDefault(); window.dispatchEvent(new Event(OPEN_EXPERT_SETTINGS)); }}
    className={cn('inline-flex h-8 shrink-0 items-center gap-1 rounded-full text-[12px] font-medium transition-all duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-60',
      enabled ? 'min-w-8 justify-center bg-brand-soft px-2 text-brand @[640px]:px-2.5' : 'w-8 justify-center text-fg-3 hover:bg-hover hover:text-fg')}>
    <Zap size={15} className={cn('transition-transform', enabled && 'fill-current')} />
    {enabled && <span className="hidden @[640px]:inline">专家</span>}
  </button>;
}
