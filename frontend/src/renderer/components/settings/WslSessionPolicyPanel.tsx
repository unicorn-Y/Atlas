import { useEffect, useState } from 'react';
import { Check, LoaderCircle } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';

type WslPolicy = { enabled: boolean; require_isolation: boolean; runtime_is_wsl: boolean; runtime: string };

export default function WslSessionPolicyPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [policy, setPolicy] = useState<WslPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { let active = true; void api<WslPolicy>(apiBaseUrl, '/api/settings/wsl-policy').then((value) => { if (active) setPolicy(value); }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : String(cause)); }); return () => { active = false; }; }, [apiBaseUrl]);
  const save = async () => {
    if (!policy || busy) return;
    setBusy(true); setError(''); setMessage('');
    try { setPolicy(await api<WslPolicy>(apiBaseUrl, '/api/settings/wsl-policy', { method: 'PUT', json: { enabled: policy.enabled, require_isolation: policy.require_isolation } })); setMessage('已保存到本机设置。'); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <section aria-label="WSL 会话策略" className="rounded-2xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]">
    <h3 className="m-0 text-[15px] font-semibold text-heading">WSL 会话策略</h3>
    <p className="m-0 mt-1 mb-3 text-[12.5px] text-fg-3">策略只约束运行在 WSL 中的 Atlas 会话，与环境识别及超时设置分开。当前运行时：{policy?.runtime === 'wsl' ? 'WSL' : policy ? '原生环境' : '读取中'}。</p>
    {policy && <div className="grid gap-2">
      <label className="flex items-start gap-2 text-[13px] text-fg-2"><input type="checkbox" checked={policy.enabled} onChange={(event) => setPolicy({ ...policy, enabled: event.target.checked })} /><span>允许在 WSL 中启动会话<small className="block text-[12px] text-fg-3">关闭后，运行在 WSL 的 Atlas 会拒绝新任务。</small></span></label>
      <label className="flex items-start gap-2 text-[13px] text-fg-2"><input type="checkbox" checked={policy.require_isolation} onChange={(event) => setPolicy({ ...policy, require_isolation: event.target.checked })} /><span>强制使用 Docker 隔离运行时<small className="block text-[12px] text-fg-3">开启后，WSL 中每个 Atlas Agent 会话都使用 Docker 沙箱；Docker 不可用时会明确失败。</small></span></label>
      <div className="flex items-center gap-2"><Button variant="secondary" disabled={busy || !policy} onClick={() => void save()}>{busy ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}保存策略</Button>{message && <span role="status" className="text-[12px] text-ok">{message}</span>}{error && <span role="alert" className="text-[12px] text-danger">{error}</span>}</div>
    </div>}
  </section>;
}
