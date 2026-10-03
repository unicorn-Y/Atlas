import { useEffect, useMemo, useState } from 'react';
import {
  Cpu, CircleMinus, Download, FolderOpen, HardDrive, LoaderCircle, MemoryStick, Pause,
  Play, Power, RefreshCw, Search, Trash2, Wrench,
} from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { localModelsApi, type LocalCatalogRow } from '../../services/persistentApi';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { field } from '../agents/shared';

const gb = (bytes?: number | null) => typeof bytes === 'number' && bytes > 0 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : '—';

const jobActive = (status?: string) => ['running', 'pending', 'downloading', 'active'].includes(String(status ?? '').toLowerCase());

/** 设置 → 本地模型：硬件 / runtime / 目录+搜索+下载 / GGUF 导入 / 激活（带诊断）/ 服务器。 */
export default function LocalModelsSettings({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const status = useAtlasStore((state) => state.localStatus);
  const hardware = useAtlasStore((state) => state.localHardware);
  const backends = useAtlasStore((state) => state.localBackends);
  const catalog = useAtlasStore((state) => state.localCatalog);
  const jobs = useAtlasStore((state) => state.localJobs);
  const activation = useAtlasStore((state) => state.localActivation);
  const busy = useAtlasStore((state) => state.localModelsBusy);
  const error = useAtlasStore((state) => state.localModelsError);
  const loadLocalModels = useAtlasStore((state) => state.loadLocalModels);
  const refreshLocalJobs = useAtlasStore((state) => state.refreshLocalJobs);
  const installLocalRuntime = useAtlasStore((state) => state.installLocalRuntime);
  const startModelDownload = useAtlasStore((state) => state.startModelDownload);
  const sideloadLocalModel = useAtlasStore((state) => state.sideloadLocalModel);
  const activateLocalModel = useAtlasStore((state) => state.activateLocalModel);
  const ejectLocalModel = useAtlasStore((state) => state.ejectLocalModel);
  const localModelServerAction = useAtlasStore((state) => state.localModelServerAction);
  const pauseOrResumeDownload = useAtlasStore((state) => state.pauseOrResumeDownload);

  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Array<Record<string, unknown>>>([]);
  const [searching, setSearching] = useState(false);
  const [ggufPath, setGgufPath] = useState('');
  const [diag, setDiag] = useState('');

  useEffect(() => { void loadLocalModels(); }, [loadLocalModels]);
  // 有活动任务时轮询进度；全部结束自动停。
  const active = jobs.some((job) => jobActive(job.status));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void refreshLocalJobs(), 3000);
    return () => window.clearInterval(timer);
  }, [active, refreshLocalJobs]);

  const models = useMemo(() => status?.models ?? [], [status]);
  const installed = new Set([...catalog.filter((row) => row.downloaded).map((row) => row.downloaded_model_id ?? row.model_id ?? row.id), ...models.map((model) => model.id)]);

  const search = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    try { setHits((await localModelsApi.search(apiBaseUrl, q, 8)).hits); }
    catch (exc) { onToast(exc instanceof Error ? exc.message : String(exc)); }
    setSearching(false);
  };
  const hitId = (hit: Record<string, unknown>) => String(hit.id ?? hit.model_id ?? hit.repo ?? hit.name ?? '');

  const showDiagnostics = async (jobId?: string) => {
    try { setDiag(JSON.stringify(await localModelsApi.diagnostics(apiBaseUrl, jobId), null, 2)); }
    catch (exc) { setDiag(exc instanceof Error ? exc.message : String(exc)); }
  };

  const catalogCard = (row: LocalCatalogRow) => {
    const id = row.downloaded_model_id ?? row.model_id ?? row.id;
    const isDownloaded = row.downloaded || installed.has(id);
    return <div key={row.id} className="rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <header className="flex items-center gap-2">
        <b className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-fg">{row.display_name || row.id}</b>
        {row.recommended && <span className="shrink-0 rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] text-fg">推荐</span>}
        {isDownloaded && <span className="shrink-0 rounded-full bg-ok-soft px-2 py-0.5 text-[10.5px] text-fg">已下载</span>}
      </header>
      <p className="mb-2 mt-1 text-[12px] leading-[1.6] text-fg-3">{row.fit_summary || row.description || ''}
        {row.size_label ? ` · ${row.size_label}` : ''}{row.quant ? ` · ${row.quant}` : ''}{row.vision ? ' · 支持视觉' : ''}</p>
      <div className="flex items-center gap-2">
        {!isDownloaded
          ? <Button size="sm" variant="secondary" onClick={() => void startModelDownload(id).then((ok) => onToast(ok ? '开始下载，进度在下方' : '没有开始下载'))}><Download size={13} />下载</Button>
          : <Button size="sm" variant="primary" disabled={busy} onClick={() => void activateLocalModel(id).then((ok) => onToast(ok ? `已激活 ${row.display_name || id}` : '激活没有通过（见下方诊断）'))}><Power size={13} />激活</Button>}
        {isDownloaded && <>
          <Button size="sm" variant="ghost" disabled={busy || status?.active_model_id !== id} onClick={() => void ejectLocalModel(id).then(() => onToast('已卸载'))}><CircleMinus size={13} />卸载</Button>
          <Button size="sm" variant="ghost" onClick={() => { void localModelsApi.deleteModel(apiBaseUrl, id).then(() => { onToast('已删除模型文件'); void loadLocalModels(); }).catch((exc) => onToast(exc instanceof Error ? exc.message : String(exc))); }}><Trash2 size={13} />删除</Button>
        </>}
      </div>
    </div>;
  };

  return <div className="grid max-w-[720px] gap-5 text-[13px] text-fg-2">
    <p className="m-0 text-[12.5px] leading-[1.6] text-fg-3">
      让 Atlas 完全离线干活：下载一个能在你显卡/内存里跑得动的开源模型，激活后可以设为默认模型（去「模型与服务」页把它选上）。想用 Ollama / LM Studio 的话，走「模型与服务」页的本机模型入口，两边不冲突。
    </p>

    {error && <p role="alert" className="m-0 rounded-xl bg-danger-soft px-3.5 py-2.5 text-[12.5px] text-danger">{error}</p>}

    <section aria-label="当前状态与服务器" className="rounded-[14px] bg-sunken px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <header className="flex flex-wrap items-center gap-2.5">
        <Cpu size={16} className="text-brand" />
        <b className="font-medium text-fg">本地推理</b>
        <span className="flex-1" />
        {status?.server_running
          ? <Button size="sm" variant="ghost" onClick={() => void localModelServerAction('stop').then((ok) => onToast(ok ? '本地服务器已停止' : '停止失败'))}><Power size={13} />停止服务器</Button>
          : <Button size="sm" variant="secondary" onClick={() => void localModelServerAction('start').then((ok) => onToast(ok ? '本地服务器已启动' : '启动失败'))}><Play size={13} />启动服务器</Button>}
        <Button size="icon-sm" variant="ghost" aria-label="刷新" onClick={() => void loadLocalModels()}>{busy ? <LoaderCircle className="spin" /> : <RefreshCw />}</Button>
      </header>
      <div className="mt-2 grid gap-x-6 gap-y-1 text-[12.5px] text-fg-3 sm:grid-cols-2">
        <span>运行时：{status?.runtime_installed ? `已安装（${status.runtime_backend ?? '默认'}）` : '未安装'}</span>
        <span>服务器：{status?.server_running ? `运行中 · ${status.server_base_url ?? ''}` : '未运行'}</span>
        <span>激活模型：{status?.active_model_id ?? '没有'}</span>
        <span>模型目录：{status?.models_dir ?? '—'}</span>
      </div>
    </section>

    <section aria-label="硬件" className="grid gap-2 sm:grid-cols-3">
      <div className="rounded-xl bg-sunken px-3.5 py-3 shadow-[inset_0_0_0_1px_var(--line)]">
        <p className="m-0 flex items-center gap-1.5 text-[12px] text-fg-3"><HardDrive size={13} />显存</p>
        <b className="text-[14px] font-medium text-fg">{hardware?.vram_label ?? gb(hardware?.vram_total_bytes)}</b>
      </div>
      <div className="rounded-xl bg-sunken px-3.5 py-3 shadow-[inset_0_0_0_1px_var(--line)]">
        <p className="m-0 flex items-center gap-1.5 text-[12px] text-fg-3"><MemoryStick size={13} />内存{hardware?.uma ? '（统一内存）' : ''}</p>
        <b className="text-[14px] font-medium text-fg">{gb(hardware?.ram_total_bytes)}</b>
      </div>
      <div className="rounded-xl bg-sunken px-3.5 py-3 shadow-[inset_0_0_0_1px_var(--line)]">
        <p className="m-0 flex items-center gap-1.5 text-[12px] text-fg-3"><Cpu size={13} />显卡</p>
        <b className="truncate text-[13px] font-medium text-fg" title={hardware?.gpu_name ?? ''}>{hardware?.gpu_name || '未检测到独显'}</b>
      </div>
    </section>

    <section aria-label="运行时" className="grid gap-2">
      <b className="px-1 font-medium text-fg">推理运行时</b>
      {backends.map((backend) => <div key={backend.backend} className="flex items-center gap-2.5 rounded-xl bg-sunken px-3.5 py-2.5 text-[12.5px] shadow-[inset_0_0_0_1px_var(--line)]">
        <Wrench size={14} className={cn('shrink-0', backend.installed ? 'text-ok' : 'text-fg-3')} />
        <b className="shrink-0 font-medium text-fg">{backend.backend}</b>
        <span className="min-w-0 flex-1 truncate text-fg-3">
          {backend.installed ? `已安装${backend.installed_tag ? ` · ${backend.installed_tag}` : ''}`
            : backend.available === false ? `装不了：${backend.unavailable_reason ?? '不支持这台机器'}` : '未安装'}
        </span>
        {!backend.installed && backend.available !== false && <Button size="sm" variant="secondary" disabled={busy}
          onClick={() => void installLocalRuntime(backend.backend).then((ok) => onToast(ok ? '开始安装运行时' : '没有开始安装'))}>安装</Button>}
      </div>)}
      {!backends.length && <p className="m-0 px-1 text-[12px] text-fg-3">还没有读到运行时目录。</p>}
    </section>

    <section aria-label="模型目录" className="grid gap-2.5">
      <b className="px-1 font-medium text-fg">推荐模型</b>
      <div className="grid gap-2.5 sm:grid-cols-2">{catalog.filter((row) => row.recommended).map(catalogCard)}</div>
      <details>
        <summary className="cursor-pointer select-none px-1 text-[12.5px] text-fg-3 hover:text-fg-2">全部模型（{catalog.length}）</summary>
        <div className="mt-2 grid gap-2.5 sm:grid-cols-2">{catalog.filter((row) => !row.recommended).map(catalogCard)}</div>
      </details>
    </section>

    <section aria-label="搜索 Hugging Face" className="grid gap-2">
      <b className="px-1 font-medium text-fg">从 Hugging Face 找</b>
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void search(); }}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="比如 Qwen3-8B GGUF" className={cn(field, 'min-w-0 flex-1')} />
        <Button type="submit" variant="secondary" disabled={searching || !query.trim()}>{searching ? <LoaderCircle size={14} className="spin" /> : <Search size={14} />}搜索</Button>
      </form>
      {hits.map((hit, index) => <div key={index} className="flex items-center gap-2.5 rounded-xl bg-sunken px-3.5 py-2 text-[12.5px] shadow-[inset_0_0_0_1px_var(--line)]">
        <span className="min-w-0 flex-1 truncate">{String(hit.name ?? hit.id ?? hitId(hit))}</span>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void startModelDownload(hitId(hit)).then((ok) => onToast(ok ? '开始下载' : '没有开始下载'))}><Download size={13} />下载</Button>
      </div>)}
    </section>

    {(jobs.length > 0) && <section aria-label="下载任务" className="grid gap-2">
      <b className="px-1 font-medium text-fg">任务</b>
      {jobs.map((job) => <div key={job.job_id} className="rounded-xl bg-sunken px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <div className="flex items-center gap-2.5 text-[12.5px]">
          <b className="min-w-0 flex-1 truncate font-medium text-fg">{job.label || job.model_id || job.job_id}</b>
          <span className="shrink-0 text-fg-3">{typeof job.percent === 'number' ? `${Math.round(job.percent)}%` : job.status}</span>
          {job.can_pause && <Button size="icon-sm" variant="ghost" aria-label="暂停下载" onClick={() => void pauseOrResumeDownload(job.job_id, 'pause')}><Pause /></Button>}
          {job.can_resume && <Button size="icon-sm" variant="ghost" aria-label="继续下载" onClick={() => void pauseOrResumeDownload(job.job_id, 'resume')}><Play /></Button>}
          {String(job.status) === 'failed' && <Button size="icon-sm" variant="ghost" aria-label="看诊断" onClick={() => void showDiagnostics(job.job_id)}><Wrench /></Button>}
        </div>
        {typeof job.percent === 'number' && <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-line">
          <i className="block h-full rounded-full bg-brand transition-[width] duration-500" style={{ width: `${Math.min(100, Math.max(2, job.percent))}%` }} />
        </div>}
        {(job.detail || job.error) && <p className="mb-0 mt-1 text-[11.5px] text-fg-3">{job.error || job.detail}</p>}
      </div>)}
    </section>}

    <section aria-label="导入 GGUF" className="grid gap-2">
      <b className="px-1 font-medium text-fg">导入本机 GGUF</b>
      <div className="flex gap-2">
        <input value={ggufPath} onChange={(event) => setGgufPath(event.target.value)} placeholder="D:\models\qwen3-8b-q4.gguf" className={cn(field, 'min-w-0 flex-1 font-mono text-[12.5px]')} />
        <Button variant="secondary" disabled={!ggufPath.trim() || busy}
          onClick={() => { const path = ggufPath.trim(); void sideloadLocalModel(path).then((ok) => onToast(ok ? '已导入，可在目录里激活' : '导入失败')); }}>
          <FolderOpen size={14} />导入
        </Button>
      </div>
      <small className="px-1 text-[11.5px] text-fg-3">直接指向一个本机的 .gguf 文件，不用下载。</small>
    </section>

    {activation && !activation.ok && <section aria-label="激活诊断" className="rounded-[14px] bg-danger-soft px-4 py-3.5">
      <b className="font-medium text-danger">激活 {activation.model_id} 没有通过</b>
      <ul className="mb-0 mt-1.5 grid list-disc gap-1 pl-5 text-[12.5px] text-danger">
        {activation.diagnostics.map((line, index) => <li key={index}>{line}</li>)}
      </ul>
      <p className="mb-0 mt-2 text-[11.5px] text-danger opacity-80">
        常见原因：tool-call 探测失败（模型不支持工具调用）、显卡驱动或 VC Redist 缺失、显存/内存不够。
      </p>
    </section>}

    <div className="flex justify-end">
      <Button variant="ghost" onClick={() => void showDiagnostics().then(() => onToast('诊断已生成'))}>生成诊断报告</Button>
    </div>
    {diag && <pre className="m-0 max-h-52 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-sunken p-3 font-mono text-[11.5px] leading-[1.6] text-fg-3">{diag}</pre>}
  </div>;
}
