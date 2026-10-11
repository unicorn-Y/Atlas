import { useCallback, useEffect, useState } from 'react';
import { Check, Download, LoaderCircle, RefreshCw, Server } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';

interface OllamaModel {
  name: string;
  size?: number | null;
  modified_at?: string;
  details?: {
    family?: string;
    parameter_size?: string;
    quantization_level?: string;
  };
}

interface OllamaPullJob {
  job_id: string;
  name: string;
  status: string;
  detail?: string;
  percent?: number | null;
  completed?: number | null;
  total?: number | null;
}

interface LocalModelsPanelProps {
  apiBaseUrl: string;
}

const bytes = (value?: number | null) => {
  if (!value || value <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

export default function LocalModelsPanel({ apiBaseUrl }: LocalModelsPanelProps) {
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [modelName, setModelName] = useState('');
  const [job, setJob] = useState<OllamaPullJob | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [registering, setRegistering] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await api<{ models: OllamaModel[] }>(apiBaseUrl, '/api/local/models/ollama/tags');
      setModels(result.models);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!job || !['pending', 'connecting', 'downloading'].includes(job.status)) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const latest = await api<OllamaPullJob>(apiBaseUrl, `/api/local/models/ollama/jobs/${encodeURIComponent(job.job_id)}`);
        if (cancelled) return;
        setJob(latest);
        if (latest.status === 'completed') {
          setNotice(`已下载 ${latest.name}。`);
          void refresh();
          return;
        }
        if (latest.status === 'failed') return;
        timer = window.setTimeout(() => { void poll(); }, 1000);
      } catch (exc) {
        if (cancelled) return;
        setError(exc instanceof Error ? exc.message : String(exc));
        timer = window.setTimeout(() => { void poll(); }, 2000);
      }
    };
    timer = window.setTimeout(() => { void poll(); }, 500);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [apiBaseUrl, job?.job_id, job?.status, refresh]);

  const pull = async () => {
    const name = modelName.trim();
    if (!name || starting) return;
    setStarting(true);
    setError('');
    setNotice('');
    try {
      const started = await api<{ job_id: string; name: string }>(apiBaseUrl, '/api/local/models/ollama/pull', {
        method: 'POST', json: { name },
      });
      setJob({ job_id: started.job_id, name: started.name, status: 'pending', detail: '等待连接 Ollama…' });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setStarting(false);
    }
  };

  const register = async (name: string) => {
    if (registering) return;
    setRegistering(name);
    setError('');
    setNotice('');
    try {
      const result = await api<{ id: string; name: string; added: boolean }>(apiBaseUrl, '/api/local/models/ollama/activate', {
        method: 'POST', json: { name },
      });
      setNotice(result.added
        ? `${result.name} 已加入 Atlas 本机模型路由；到“模型与服务”选择它即可设为当前模型。`
        : `${result.name} 已在 Atlas 本机模型路由中。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRegistering('');
    }
  };

  const pulling = starting || Boolean(job && ['pending', 'connecting', 'downloading'].includes(job.status));

  return (
    <section className="grid max-w-[760px] gap-4 rounded-xl border border-line bg-surface p-4 text-[13px] text-fg-2" aria-label="Ollama 本地模型">
      <header className="flex flex-wrap items-center gap-2">
        <Server size={15} className="text-brand" />
        <h3 className="m-0 flex-1 text-sm font-semibold text-fg">Ollama 本地模型</h3>
        <Button type="button" size="sm" variant="ghost" disabled={loading} onClick={() => void refresh()}>
          {loading ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />}刷新
        </Button>
      </header>

      <p className="m-0 text-xs leading-5 text-fg-3">
        只连接本机 127.0.0.1:11434，不扫描局域网。下载只会在你按“下载”后请求本机 Ollama；Ollama 随后从其模型库拉取。
        添加到 Atlas 只登记 OpenAI-compatible 本机路由，不修改 provider 密钥，也不会自动切换当前模型。
      </p>

      {error && <p className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger" role="alert">{error}</p>}
      {notice && <p className="m-0 rounded-lg bg-ok-soft px-3 py-2 text-xs text-fg" role="status">{notice}</p>}

      <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); void pull(); }}>
        <input
          aria-label="Ollama 模型名称"
          className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-sunken px-3 text-[12.5px] text-fg placeholder:text-fg-3"
          value={modelName}
          maxLength={256}
          onChange={(event) => setModelName(event.target.value)}
          placeholder="例如 qwen3.5:latest"
        />
        <Button type="submit" size="sm" variant="secondary" disabled={pulling || !modelName.trim()}>
          {pulling ? <LoaderCircle size={14} className="animate-spin" /> : <Download size={14} />}下载模型
        </Button>
      </form>

      {job && <div className="grid gap-1 rounded-lg bg-sunken px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]" role="status">
        <div className="flex items-center gap-2 text-xs">
          <span className="min-w-0 flex-1 truncate font-medium text-fg">{job.name}</span>
          <span className={job.status === 'failed' ? 'text-danger' : 'text-fg-3'}>{job.detail || job.status}</span>
          {job.status === 'completed' && <Check size={14} className="text-ok" />}
          {typeof job.percent === 'number' && <span className="tabular-nums text-fg-3">{job.percent}%</span>}
        </div>
        {typeof job.percent === 'number' && <div className="h-1 overflow-hidden rounded-full bg-line">
          <i className="block h-full rounded-full bg-brand transition-[width]" style={{ width: `${job.percent}%` }} />
        </div>}
        {job.total && <p className="m-0 text-[10.5px] text-fg-3">{bytes(job.completed)} / {bytes(job.total)}</p>}
      </div>}

      <div className="grid gap-2">
        <b className="text-xs font-medium text-fg">已安装模型（{models.length}）</b>
        {!models.length && !loading && !error && <p className="m-0 text-xs text-fg-3">本机 Ollama 尚未安装模型。</p>}
        {models.map((model) => {
          const details = [model.details?.family, model.details?.parameter_size, model.details?.quantization_level].filter(Boolean).join(' · ');
          return <div key={model.name} className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]">
            <div className="min-w-0 flex-1">
              <b className="block truncate text-[12.5px] font-medium text-fg">{model.name}</b>
              <span className="text-[10.5px] text-fg-3">{[details, bytes(model.size)].filter(Boolean).join(' · ') || '本机已安装'}</span>
            </div>
            <Button type="button" size="sm" variant="secondary" disabled={Boolean(registering)} onClick={() => void register(model.name)}>
              {registering === model.name ? <LoaderCircle size={13} className="animate-spin" /> : null}添加到 Atlas
            </Button>
          </div>;
        })}
      </div>
    </section>
  );
}
