import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../../services/api';

type Payload = { config: { models?: { default?: string; gateway?: { base_url?: string } } }; api_key_configured: boolean };

export default function ConversationModelSettings({ apiBaseUrl, conversationId, onToast }: {
  apiBaseUrl: string; conversationId: string; onToast: (text: string) => void;
}) {
  const [state, setState] = useState<Payload | null>(null);
  const [models, setModels] = useState<Array<{ id: string; name: string }>>([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const path = `/api/conversations/${encodeURIComponent(conversationId)}/settings`;

  const load = async () => {
    const [saved, catalog] = await Promise.all([
      api<Payload>(apiBaseUrl, path),
      api<{ models: Array<{ id: string; name: string }> }>(apiBaseUrl, '/api/models'),
    ]);
    setState(saved); setModels(catalog.models);
    setDefaultModel(saved.config.models?.default ?? '');
    setBaseUrl(saved.config.models?.gateway?.base_url ?? '');
  };
  useEffect(() => { void load().catch((exc) => setError(exc instanceof Error ? exc.message : String(exc))); }, [apiBaseUrl, conversationId]);

  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const body: Record<string, string> = { default_model: defaultModel, gateway_base_url: baseUrl };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      setState(await api<Payload>(apiBaseUrl, path, { method: 'PUT', json: body }));
      setApiKey(''); onToast('会话模型设置已保存');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const clear = async () => {
    setBusy(true); setError('');
    try { setState(await api<Payload>(apiBaseUrl, path, { method: 'PUT', json: { clear_api_key: true } })); onToast('已清除会话专用密钥'); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };

  return <form onSubmit={(event) => void save(event)} className="mt-4 grid gap-2 rounded-xl border border-line bg-sunken/40 p-3" aria-label="会话模型与凭据">
    <h4 className="m-0 text-[12px] font-medium">当前会话的模型与凭据</h4>
    <p className="m-0 text-[10.5px] text-fg-3">单独的会话设置优先；未设置的字段沿用所属项目或 Atlas 默认值。密钥保存在系统凭据库。</p>
    {error && <p role="alert" className="m-0 text-[11px] text-danger">{error}</p>}
    <label className="grid gap-1 text-[11px]">默认模型<select value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} className="h-8 rounded-lg bg-surface px-2 text-fg"><option value="">沿用所属项目或 Atlas 设置</option>{models.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <label className="grid gap-1 text-[11px]">网关地址<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="沿用所属项目或 Atlas 设置" className="h-8 rounded-lg bg-surface px-2 text-fg" /></label>
    <label className="grid gap-1 text-[11px]">会话 API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={state?.api_key_configured ? '已设置（输入新值轮换）' : '可选的会话专用密钥'} className="h-8 rounded-lg bg-surface px-2 text-fg" /></label>
    <div className="flex justify-between"><small className="self-center text-[10px] text-fg-3">{state?.api_key_configured ? '会话密钥已配置' : '使用上级密钥或 Atlas 默认密钥'}</small><div className="flex gap-2"><button type="button" disabled={busy || !state?.api_key_configured} onClick={() => void clear()} className="rounded px-2 text-[10.5px] text-fg-3 hover:bg-hover">清除专用密钥</button><button type="submit" disabled={busy} className="h-7 rounded-lg bg-brand px-3 text-[11px] text-white">{busy ? '保存中…' : '保存会话设置'}</button></div></div>
  </form>;
}
