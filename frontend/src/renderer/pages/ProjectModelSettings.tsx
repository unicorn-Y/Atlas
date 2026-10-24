import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../services/api';

interface ProjectSettings {
  config: { models?: { default?: string; gateway?: { base_url?: string } } };
  api_key_configured: boolean;
  credential_scope: string;
}

export default function ProjectModelSettings({ projectId, apiBaseUrl, onToast }: {
  projectId: string; apiBaseUrl: string; onToast: (text: string) => void;
}) {
  const [settings, setSettings] = useState<ProjectSettings | null>(null);
  const [models, setModels] = useState<Array<{ id: string; name: string }>>([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = () => Promise.all([
    api<ProjectSettings>(apiBaseUrl, `/api/projects/${encodeURIComponent(projectId)}/settings`),
    api<{ models: Array<{ id: string; name: string }> }>(apiBaseUrl, '/api/models'),
  ]).then(([project, catalog]) => {
    setSettings(project);
    setDefaultModel(project.config.models?.default ?? '');
    setBaseUrl(project.config.models?.gateway?.base_url ?? '');
    setModels(catalog.models);
  });

  useEffect(() => { void load().catch((exc) => setError(exc instanceof Error ? exc.message : String(exc))); }, [apiBaseUrl, projectId]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const payload: Record<string, string> = { default_model: defaultModel, gateway_base_url: baseUrl };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      const saved = await api<ProjectSettings>(apiBaseUrl, `/api/projects/${encodeURIComponent(projectId)}/settings`, { method: 'PUT', json: payload });
      setSettings(saved); setApiKey(''); onToast('项目模型设置已保存，密钥保存在系统凭据库中');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };

  const clearKey = async () => {
    setBusy(true); setError('');
    try { const saved = await api<ProjectSettings>(apiBaseUrl, `/api/projects/${encodeURIComponent(projectId)}/settings`, { method: 'PUT', json: { clear_api_key: true } }); setSettings(saved); setApiKey(''); onToast('已清除此项目的专用密钥'); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };

  return <form onSubmit={(event) => void save(event)} className="my-4 grid gap-2 rounded-xl border border-line bg-sunken/40 p-3" aria-label="项目模型和凭据">
    <h3 className="m-0 text-[13px]">项目模型与凭据</h3>
    <p className="m-0 text-[11px] text-fg-3">此密钥只供「{projectId}」项目下的会话使用，存放在系统凭据库，不回退到其他项目的密钥。</p>
    {error && <p role="alert" className="m-0 text-[11px] text-danger">{error}</p>}
    <label className="grid gap-1 text-[11px]">项目默认模型
      <select value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} className="h-8 rounded-lg bg-surface px-2 text-fg">
        <option value="">沿用 Atlas 全局模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
      </select>
    </label>
    <label className="grid gap-1 text-[11px]">项目网关地址
      <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="留空时沿用默认地址" className="h-8 rounded-lg bg-surface px-2 text-fg" />
    </label>
    <label className="grid gap-1 text-[11px]">项目 API 密钥
      <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" placeholder={settings?.api_key_configured ? '已设置（输入新值即可轮换）' : '仅保存到本项目'} className="h-8 rounded-lg bg-surface px-2 text-fg" />
    </label>
    <div className="flex items-center justify-between">
      <small className="text-[10px] text-fg-3">{settings?.api_key_configured ? '项目密钥已配置' : '项目密钥未配置'}</small>
      <div className="flex gap-2"><button type="button" disabled={busy || !settings?.api_key_configured} onClick={() => void clearKey()} className="h-7 rounded-lg px-2 text-[11px] text-fg-3 hover:bg-hover">清除项目密钥</button><button type="submit" disabled={busy} className="h-7 rounded-lg bg-brand px-3 text-[11px] text-white">{busy ? '保存中…' : '保存项目设置'}</button></div>
    </div>
  </form>;
}
