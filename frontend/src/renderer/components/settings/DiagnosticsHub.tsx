import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';
import LocalMaintenancePanel from './LocalMaintenancePanel';

type SourceRow = { key: string; value: unknown; sources: Array<{ source: string; value: unknown; active: boolean }> };
type AlertRow = { id: string; category: string; title: string; detail: string; target: string; read: boolean; created_at: string };
type TaskRow = { id: string; kind: string; name: string; status: string; stoppable?: boolean; cpu_percent?: number | null; memory_bytes?: number | null; model?: string; duration_ms?: number; input_tokens?: number; output_tokens?: number; cached_tokens?: number; recent_tools?: Array<{ name: string; duration_ms: number; running?: boolean }> };

export default function DiagnosticsHub({ apiBaseUrl, workspacePath = '' }: { apiBaseUrl: string; workspacePath?: string }) {
  const [tab, setTab] = useState<'sources' | 'alerts' | 'debug' | 'tasks' | 'maintenance'>('sources');
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [unread, setUnread] = useState(0);
  const [queueLength, setQueueLength] = useState(0);
  const [error, setError] = useState('');
  const [updateChannel, setUpdateChannel] = useState<'release' | 'source'>(() => localStorage.getItem('atlas.preference.update-channel') === 'source' ? 'source' : 'release');
  const [releaseSource, setReleaseSource] = useState(() => localStorage.getItem('atlas.preference.release-source') ?? '');
  const [releaseStatus, setReleaseStatus] = useState('');
  const refresh = useCallback(async () => {
    try {
      const [sourceData, alertData, taskData] = await Promise.all([
        api<{ sources: SourceRow[] }>(apiBaseUrl, `/api/diagnostics/config-sources${workspacePath ? `?root=${encodeURIComponent(workspacePath)}` : ''}`),
        api<{ alerts: AlertRow[]; unread: number }>(apiBaseUrl, '/api/diagnostics/alerts'),
        api<{ tasks: TaskRow[]; event_queue_length: number }>(apiBaseUrl, '/api/diagnostics/tasks'),
      ]);
      setSources(sourceData.sources); setAlerts(alertData.alerts); setUnread(alertData.unread); setTasks(taskData.tasks); setQueueLength(taskData.event_queue_length); setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  }, [apiBaseUrl, workspacePath]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { if (tab === 'debug' || tab === 'tasks') void refresh(); }, 1500); return () => window.clearInterval(timer); }, [refresh, tab]);
  useEffect(() => { const select = (event: Event) => { const next = (event as CustomEvent<string>).detail; if (next === 'sources' || next === 'alerts' || next === 'debug' || next === 'tasks' || next === 'maintenance') setTab(next); }; window.addEventListener('atlas:diagnostics-tab', select); return () => window.removeEventListener('atlas:diagnostics-tab', select); }, []);
  const markRead = async (id: string) => { await api(apiBaseUrl, `/api/diagnostics/alerts/${encodeURIComponent(id)}/read`, { method: 'POST' }); await refresh(); };
  const stop = async (id: string) => { await api(apiBaseUrl, `/api/diagnostics/tasks/${encodeURIComponent(id)}/stop`, { method: 'POST' }); await refresh(); };
  const tabs = [['sources', '配置来源树'], ['alerts', `告警中心${unread ? ` (${unread})` : ''}`], ['debug', '实时调试'], ['tasks', '任务管理器'], ['maintenance', '日志与存储维护']] as const;
  return <section className="mt-5 rounded-xl border border-line bg-surface p-4" aria-label="状态与诊断中心">
    <h3 className="m-0 mb-2 text-[14px] font-semibold text-heading">状态与诊断中心</h3>
    <nav className="mb-3 flex flex-wrap gap-1 border-b border-line pb-2" aria-label="诊断工具">
      {tabs.map(([id, label]) => <button key={id} type="button" onClick={() => { setTab(id); void refresh(); }} className={`rounded-md px-2.5 py-1.5 text-[12px] ${tab === id ? 'bg-hover text-fg' : 'text-fg-3 hover:text-fg'}`}>{label}</button>)}
    </nav>
    {error && <p role="alert" className="text-danger">读取诊断数据失败：{error}</p>}
    {tab === 'sources' && <>
      <p className="text-[11.5px] text-fg-3">展示本机配置文件中的值及覆盖顺序。敏感值已隐藏；项目 .atlas/ 和命令行覆盖会在工作区/启动参数来源中标注。</p>
      <ul className="grid max-h-80 gap-2 overflow-auto">{sources.map((row) => <li key={row.key} className="rounded-lg bg-sunken p-2 text-[11.5px]"><strong>{row.key}</strong><div>生效值：{String(row.value)}</div>{row.sources.map((source) => <div key={source.source} className={source.active ? 'text-brand' : 'text-fg-3'}>{source.active ? '✓' : '↳'} {source.source}：{String(source.value)}{!source.active && '（被覆盖）'}</div>)}</li>)}</ul>
    </>}
    {tab === 'alerts' && <>
      <p className="text-[11.5px] text-fg-3">未读 {unread} 条 · 本机保留最近 500 条告警。</p>
      <ul className="grid max-h-80 gap-2 overflow-auto">{alerts.map((alert) => <li key={alert.id} className="rounded-lg bg-sunken p-2 text-[12px]"><div className="flex justify-between gap-2"><strong>{alert.title}</strong><time className="text-[10px] text-fg-3">{new Date(alert.created_at).toLocaleString()}</time></div><p className="my-1 whitespace-pre-wrap text-fg-2">{alert.detail}</p><div className="flex gap-3"><button type="button" onClick={() => void markRead(alert.id)} className="text-brand">{alert.read ? '已读' : '标记已读'}</button><button type="button" onClick={() => window.dispatchEvent(new CustomEvent('atlas:open-diagnostics-settings'))} className="text-fg-3">跳到诊断设置</button></div></li>)}</ul>
      {!alerts.length && <p className="text-[12px] text-fg-3">暂无历史告警。</p>}
    </>}
    {tab === 'debug' && <div className="grid gap-1 rounded-lg bg-sunken p-3 font-mono text-[11.5px]"><div>运行阶段：{tasks.some((task) => task.status === 'running') ? '正在执行工具/模型任务' : '空闲'}</div><div>后台活动：{tasks.length}</div><div>事件队列长度：{queueLength}</div>{tasks.filter((task) => task.model).map((task) => <div key={task.id}>最近模型请求：{task.model} · 耗时 {task.duration_ms ?? '未知'} ms · input {task.input_tokens ?? '未知'} / output {task.output_tokens ?? '未知'} token · 缓存命中 {task.cached_tokens ?? '未知'}</div>)}{tasks.flatMap((task) => task.recent_tools ?? []).slice(-8).map((tool, index) => <div key={`${tool.name}:${index}`}>工具调用：{tool.name} · {tool.duration_ms} ms{tool.running ? ' · 运行中' : ''}</div>)}<ul>{tasks.map((task) => <li key={task.id}>{task.kind} · {task.status} · {task.name}</li>)}</ul></div>}
    {tab === 'tasks' && <><p className="text-[11.5px] text-fg-3">活动任务 {tasks.length} · CPU/内存未暴露时显示“未知”。</p><ul className="grid gap-2">{tasks.map((task) => <li key={`${task.kind}:${task.id}`} className="flex items-center justify-between gap-2 rounded-lg bg-sunken p-2 text-[12px]"><span><strong>{task.kind}</strong> · {task.name}<small className="ml-2 text-fg-3">{task.status} · CPU {task.cpu_percent ?? '未知'} · 内存 {task.memory_bytes == null ? '未知' : `${Math.round(task.memory_bytes / 1048576)} MB`}</small></span>{task.stoppable && <button type="button" onClick={() => void stop(task.id)} className="text-danger">结束</button>}</li>)}</ul>{!tasks.length && <p className="text-[12px] text-fg-3">当前没有后台活动。</p>}</>}
    {tab === 'maintenance' && <LocalMaintenancePanel apiBaseUrl={apiBaseUrl} />}
    <div className="mt-4 grid gap-2 border-t border-line pt-3" aria-label="更新通道设置"><strong className="text-[12px]">更新与版本生命周期</strong>
      <label className="flex items-center gap-2 text-[11.5px]">更新通道<select aria-label="更新通道" value={updateChannel} onChange={(event) => { const channel = event.target.value as 'release' | 'source'; setUpdateChannel(channel); localStorage.setItem('atlas.preference.update-channel', channel); window.dispatchEvent(new Event('atlas:update-settings-changed')); }} className="rounded border border-line bg-surface px-2 py-1"><option value="release">发布版</option><option value="source">源码（开发者）</option></select></label>
      {updateChannel === 'release' && <><label className="grid gap-1 text-[11.5px]">GitHub Releases 最新版本 API 地址<input aria-label="发布源地址" value={releaseSource} onChange={(event) => setReleaseSource(event.target.value)} onBlur={() => { localStorage.setItem('atlas.preference.release-source', releaseSource.trim()); window.dispatchEvent(new Event('atlas:update-settings-changed')); }} placeholder="https://api.github.com/repos/<owner>/<repo>/releases/latest" className="rounded border border-line bg-surface px-2 py-1.5" /></label><p className="m-0 text-[10.5px] text-fg-3">此工作副本没有配置 GitHub origin remote 或 release 仓库元数据。填入 Atlas 仓库 Releases API 地址后，桌面端会自动检查更新。</p><button type="button" onClick={() => { localStorage.setItem('atlas.preference.release-source', releaseSource.trim()); void window.atlasDesktop?.checkReleaseUpdate?.(releaseSource.trim()).then((status) => setReleaseStatus(status.error ?? (status.available ? `发现版本 ${status.latest}` : `当前版本 ${status.current}，没有新版本`))).catch((exc) => setReleaseStatus(String(exc))); }} className="justify-self-start rounded border border-line px-2.5 py-1 text-[11px]">立即检查发布版更新</button></>}
      {releaseStatus && <p role="status" className="m-0 text-[11px] text-fg-3">{releaseStatus}</p>}
    </div>
  </section>;
}
