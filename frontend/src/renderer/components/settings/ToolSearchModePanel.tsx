import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';

type Mode = 'all' | 'on-demand';
type ModeState = { mode: Mode; source: string };

export default function ToolSearchModePanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [state, setState] = useState<ModeState>({ mode: 'on-demand', source: 'loading' });
  const [draft, setDraft] = useState<Mode>('on-demand');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void api<ModeState>(apiBaseUrl, '/api/settings/tool-search-mode').then((value) => {
      if (active) { setState(value); setDraft(value.mode); }
    }).catch((error: unknown) => { if (active) setMessage(error instanceof Error ? error.message : String(error)); });
    return () => { active = false; };
  }, [apiBaseUrl]);
  const save = async () => {
    setBusy(true); setMessage('');
    try { const value = await api<ModeState>(apiBaseUrl, '/api/settings/tool-search-mode', { method: 'PUT', json: { mode: draft } }); setState(value); setMessage('已保存到本机用户设置；新运行会使用此模式。'); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const reset = async () => {
    setBusy(true); setMessage('');
    try { const value = await api<ModeState>(apiBaseUrl, '/api/settings/tool-search-mode', { method: 'DELETE' }); setState(value); setDraft(value.mode); setMessage('已恢复配置文件默认模式。'); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  return <section className="grid gap-2 rounded-xl border border-line bg-panel p-3" aria-label="工具检索装载策略">
    <div><h4 className="m-0 text-[12.5px] font-semibold text-fg">工具检索装载策略</h4><p className="m-0 mt-1 text-[11px] text-fg-3">当前默认：{state.mode === 'all' ? '全部定义' : '按需检索'} · 来源：{state.source}</p></div>
    <label className="grid max-w-sm gap-1 text-[11px] text-fg-3">新运行使用
      <select aria-label="工具检索模式" value={draft} onChange={(event) => setDraft(event.target.value as Mode)} className="h-8 rounded-lg bg-sunken px-2 text-[12px] text-fg">
        <option value="all">全部注入完整工具定义</option><option value="on-demand">按需检索并加载匹配工具</option>
      </select>
    </label>
    <div className="flex items-center gap-2"><Button disabled={busy || state.mode === draft} onClick={() => void save()}>{busy ? '保存中…' : '保存默认模式'}</Button><Button variant="ghost" disabled={busy || state.source !== 'user-settings.json'} onClick={() => void reset()}>恢复配置默认</Button>{message && <span role="status" className="text-[10.5px] text-fg-3">{message}</span>}</div>
  </section>;
}
