import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';

type State = { enabled: boolean; permission_mode: string };

export default function ComputerUseSettingsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = () => void api<State>(apiBaseUrl, '/api/computer/settings').then(setState).catch((cause) => setError(String(cause)));
  useEffect(load, [apiBaseUrl]);
  const setEnabled = async (enabled: boolean) => {
    if (enabled && !window.confirm('授权 Computer Use 后，Agent 可按当前会话权限操作本机桌面。是否继续？')) return;
    setBusy(true); setError('');
    try { setState(await api<State>(apiBaseUrl, '/api/computer/settings', { method: 'PUT', json: { enabled } })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <section className="rounded-xl border border-edge bg-panel p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h4 className="m-0 text-[13px] font-semibold text-fg">Computer Use 授权</h4>
        <p className="mb-0 mt-1 text-[12px] text-fg-3">关闭会将本机桌面操作权限设为 deny；开启前需再次确认。</p></div>
      <Button size="sm" variant={state?.enabled ? 'secondary' : 'primary'} disabled={!state || busy} onClick={() => void setEnabled(!state?.enabled)}>
        {busy ? '保存中…' : state?.enabled ? '撤销授权' : '授权 Computer Use'}
      </Button>
    </div>
    {error && <p role="alert" className="mb-0 mt-3 text-[12px] text-danger">读取或保存失败：{error}</p>}
  </section>;
}
