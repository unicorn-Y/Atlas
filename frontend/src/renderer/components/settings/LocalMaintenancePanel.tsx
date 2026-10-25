import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../services/api';

type DataRoot = { current_root: string; previous_root: string | null; migrated_at: string | null; rollback_available: boolean };
type Preview = { source_root: string; target_root: string; file_count: number; total_bytes: number; truncated: boolean };
type Trace = { request_id: string; run_id: string; model: string; provider: string; endpoint: string; request_params: Record<string, unknown>; started_at: string; duration_ms: number | null; status: string; error_category: string | null; error_detail: string | null };
type Audit = { id: number; created_at: string; category: string; action: string; outcome: string; details: Record<string, unknown> };
type ResetCategory = { id: string; label: string; bytes: number; file_count: number; preserved: boolean; paths: string[] };
const formatBytes = (bytes: number) => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export default function LocalMaintenancePanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [root, setRoot] = useState<DataRoot | null>(null);
  const [target, setTarget] = useState('');
  const [migrationPreview, setMigrationPreview] = useState<Preview | null>(null);
  const [verifiedRoot, setVerifiedRoot] = useState('');
  const [migrationStatus, setMigrationStatus] = useState('');
  const [reportReason, setReportReason] = useState('');
  const [crashReports, setCrashReports] = useState<Array<{ id: string; created_at: string; reason: string }>>([]);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [traceQuery, setTraceQuery] = useState('');
  const [traceFilter, setTraceFilter] = useState('');
  const [audits, setAudits] = useState<Audit[]>([]);
  const [auditQuery, setAuditQuery] = useState('');
  const [auditFilter, setAuditFilter] = useState('');
  const [resetCategories, setResetCategories] = useState<ResetCategory[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [resetMessage, setResetMessage] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const refreshRoot = useCallback(async () => {
    const info = await api<DataRoot>(apiBaseUrl, '/api/maintenance/data-directory'); setRoot(info); setTarget((current) => current || '');
  }, [apiBaseUrl]);
  const refreshReports = useCallback(async () => setCrashReports((await api<{ reports: typeof crashReports }>(apiBaseUrl, '/api/maintenance/crash-reports')).reports), [apiBaseUrl]);
  const refresh = useCallback(async () => {
    setError('');
    try {
      await Promise.all([refreshRoot(), refreshReports()]);
      const [traceData, auditData, resetData] = await Promise.all([
        api<{ traces: Trace[] }>(apiBaseUrl, `/api/maintenance/model-traces?q=${encodeURIComponent(traceFilter)}`),
        api<{ events: Audit[] }>(apiBaseUrl, `/api/maintenance/audit?q=${encodeURIComponent(auditFilter)}`),
        api<{ categories: ResetCategory[] }>(apiBaseUrl, '/api/maintenance/reset/preview'),
      ]);
      setTraces(traceData.traces); setAudits(auditData.events); setResetCategories(resetData.categories);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [apiBaseUrl, auditFilter, refreshReports, refreshRoot, traceFilter]);
  useEffect(() => { void refresh(); }, [refresh]);
  const totalSelected = useMemo(() => resetCategories.filter((item) => selected.includes(item.id)).reduce((sum, item) => sum + item.bytes, 0), [resetCategories, selected]);

  const previewMigration = async () => {
    setError(''); setMigrationStatus('正在扫描源文件并计算清单…');
    try { const preview = await api<Preview>(apiBaseUrl, '/api/maintenance/data-directory/preview', { method: 'POST', json: { target } }); setMigrationPreview(preview); setTarget(preview.target_root); setMigrationStatus(''); }
    catch (cause) { setMigrationStatus(''); setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const copyMigration = async () => {
    if (!migrationPreview || migrationPreview.target_root !== target) { setError('请先为当前目标目录生成预览。'); return; }
    setError(''); setMigrationStatus('正在复制文件并逐项校验 SHA-256；请保持 Atlas 运行…');
    try {
      const result = await api<{ verified: boolean; target_root: string; file_count: number; total_bytes: number }>(apiBaseUrl, '/api/maintenance/data-directory/copy-verify', { method: 'POST', json: { target } });
      setVerifiedRoot(result.verified ? result.target_root : '');
      setMigrationStatus(result.verified ? `复制与 SHA-256 校验通过：${result.file_count} 个文件，${formatBytes(result.total_bytes)}。` : '迁移校验失败。');
    } catch (cause) { setMigrationStatus(''); setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const switchRoot = async (next: string) => {
    if (!window.atlasDesktop?.switchDataRoot) { setError('切换数据目录需要 Atlas 桌面主进程。'); return; }
    if (!window.confirm(`切换数据目录到：\n${next}\nAtlas 将关闭并重新启动。`)) return;
    setMessage('已校验目标数据；正在停止后端并重启 Atlas…');
    try { await window.atlasDesktop.switchDataRoot(next); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setMessage(''); }
  };
  const saveCrashReport = async () => {
    setError('');
    try {
      const diagnostics = await api<Record<string, unknown>>(apiBaseUrl, '/api/diagnostics');
      const result = await api<{ path: string; id: string }>(apiBaseUrl, '/api/maintenance/crash-reports', { method: 'POST', json: {
        reason: reportReason || '用户保存的本机故障报告', diagnostics: { diagnostics, user_agent: navigator.userAgent, saved_from: '本地维护面板' },
      } });
      setMessage(`故障报告已保存到本机：${result.path}`); setReportReason(''); await refreshReports();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const loadTraces = async () => { try { setTraceFilter(traceQuery); setTraces((await api<{ traces: Trace[] }>(apiBaseUrl, `/api/maintenance/model-traces?q=${encodeURIComponent(traceQuery)}`)).traces); } catch (cause) { setError(String(cause)); } };
  const loadAudit = async () => { try { setAuditFilter(auditQuery); setAudits((await api<{ events: Audit[] }>(apiBaseUrl, `/api/maintenance/audit?q=${encodeURIComponent(auditQuery)}`)).events); } catch (cause) { setError(String(cause)); } };
  const previewReset = async () => {
    try { const result = await api<{ categories: ResetCategory[] }>(apiBaseUrl, '/api/maintenance/reset/preview'); setResetCategories(result.categories); setResetMessage(`预览已更新：所选类别最多可释放 ${formatBytes(totalSelected)}。`); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const applyReset = async () => {
    if (!selected.length) { setError('请先选择资源类别。'); return; }
    if (!window.confirm(`将清理 ${selected.join('、')}，估算最多释放 ${formatBytes(totalSelected)}。会话数据库仅清理已归档且未置顶会话。继续？`)) return;
    try {
      const result = await api<{ released_bytes: number }>(apiBaseUrl, '/api/maintenance/reset', { method: 'POST', json: { categories: selected, confirm: true } });
      setResetMessage(`清理完成，释放 ${formatBytes(result.released_bytes)}。`); setSelected([]); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };

  return <div className="mt-4 grid gap-4" aria-label="本地维护">
    {error && <p role="alert" className="m-0 text-[12px] text-danger">{error}</p>}{message && <p role="status" className="m-0 text-[12px] text-brand">{message}</p>}
    <section className="grid gap-2 rounded-xl border border-line p-3" aria-label="数据目录迁移">
      <h4 className="m-0 text-[13px] font-medium">数据目录迁移</h4><p className="m-0 text-[11px] text-fg-3">复制配置与本机数据到新目录，逐文件校验 SHA-256 后切换；保留原目录供回滚。回滚会回到原目录，切换后新增的数据不会自动合并。</p>
      <p className="m-0 break-all text-[11px]">当前：{root?.current_root ?? '读取中…'}</p>{root?.previous_root && <p className="m-0 break-all text-[11px]">上次迁移源：{root.previous_root}</p>}
      <label className="grid gap-1 text-[11px]">新数据目录（绝对路径）<input aria-label="新数据目录" value={target} onChange={(event) => { setTarget(event.target.value); setMigrationPreview(null); setVerifiedRoot(''); }} placeholder="例如 D:\\AtlasData" className="rounded border border-line bg-surface px-2 py-1.5" /></label>
      <div className="flex flex-wrap gap-2"><button type="button" onClick={() => void previewMigration()} className="rounded border border-line px-2 py-1 text-[11px]">预览复制</button><button type="button" disabled={!migrationPreview} onClick={() => void copyMigration()} className="rounded border border-line px-2 py-1 text-[11px] disabled:opacity-40">复制并校验</button>{verifiedRoot === target && <button type="button" onClick={() => void switchRoot(target)} className="rounded bg-brand px-2 py-1 text-[11px] text-on-primary">切换到新目录</button>}{root?.rollback_available && root.previous_root && <button type="button" onClick={() => void switchRoot(root.previous_root!)} className="rounded border border-line px-2 py-1 text-[11px]">回滚到原目录</button>}<button type="button" onClick={() => void refresh()} className="rounded border border-line px-2 py-1 text-[11px]">刷新本机维护数据</button></div>
      {migrationPreview && <p role="status" className="m-0 break-all text-[11px] text-fg-3">{migrationPreview.file_count} 个文件 · {formatBytes(migrationPreview.total_bytes)} · 目标 {migrationPreview.target_root}{migrationPreview.truncated ? '（文件明细超过 500 项）' : ''}</p>}{migrationStatus && <p role="status" className="m-0 text-[11px] text-brand">{migrationStatus}</p>}
    </section>
    <section className="grid gap-2 rounded-xl border border-line p-3" aria-label="崩溃报告归档">
      <h4 className="m-0 text-[13px] font-medium">本机故障报告</h4><p className="m-0 text-[11px] text-fg-3">报告只写入当前数据目录，不会上传；诊断配置由后端脱敏后归档。</p>
      <textarea aria-label="故障简述" rows={2} value={reportReason} onChange={(event) => setReportReason(event.target.value)} placeholder="可写下故障现象、发生时间或复现步骤" className="rounded border border-line bg-surface p-2 text-[11px]" />
      <button type="button" onClick={() => void saveCrashReport()} className="justify-self-start rounded border border-line px-2 py-1 text-[11px]">保存本机报告</button>
      <ul className="m-0 grid gap-1 pl-5 text-[10.5px] text-fg-3">{crashReports.slice(0, 5).map((item) => <li key={item.id}>{new Date(item.created_at).toLocaleString()} · {item.reason} · {item.id}</li>)}</ul>
    </section>
    <section className="grid gap-2 rounded-xl border border-line p-3" aria-label="模型请求轨迹">
      <h4 className="m-0 text-[13px] font-medium">模型请求轨迹</h4><p className="m-0 text-[11px] text-fg-3">记录请求 ID、模型/服务、请求参数摘要、耗时与错误；不保存提示词、工具定义或凭据。</p>
      <div className="flex gap-2"><input aria-label="筛选模型轨迹" value={traceQuery} onChange={(event) => setTraceQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void loadTraces(); }} placeholder="request ID / 模型 / 状态" className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1 text-[11px]" /><button type="button" onClick={() => void loadTraces()} className="rounded border border-line px-2 py-1 text-[11px]">筛选</button></div>
      <ul className="m-0 grid max-h-52 gap-1 overflow-auto p-0">{traces.map((item) => <li key={item.request_id} className="list-none rounded bg-sunken p-2 text-[10.5px]"><b>{item.model}</b> · {item.provider} · {item.status} · {item.duration_ms ?? '运行中'} ms<div className="break-all text-fg-3">ID {item.request_id} · {new Date(item.started_at).toLocaleString()} · {item.endpoint}</div><div className="break-all text-fg-3">参数 {JSON.stringify(item.request_params)}{item.error_category ? ` · ${item.error_category}: ${item.error_detail}` : ''}</div></li>)}</ul>
    </section>
    <section className="grid gap-2 rounded-xl border border-line p-3" aria-label="用户操作审计">
      <h4 className="m-0 text-[13px] font-medium">本机操作审计</h4><div className="flex gap-2"><input aria-label="筛选审计日志" value={auditQuery} onChange={(event) => setAuditQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void loadAudit(); }} placeholder="类别 / 操作 / 结果" className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1 text-[11px]" /><button type="button" onClick={() => void loadAudit()} className="rounded border border-line px-2 py-1 text-[11px]">筛选</button></div>
      <ul className="m-0 grid max-h-44 gap-1 overflow-auto p-0">{audits.map((item) => <li key={item.id} className="list-none text-[10.5px]">{new Date(item.created_at).toLocaleString()} · {item.category}/{item.action} · {item.outcome} · {JSON.stringify(item.details)}</li>)}</ul>
    </section>
    <section className="grid gap-2 rounded-xl border border-line p-3" aria-label="资源重置预览">
      <h4 className="m-0 text-[13px] font-medium">资源重置预览</h4><p className="m-0 text-[11px] text-fg-3">先预览数量和占用，再执行所选清理；配置与凭据始终保留，会话只清理已归档且未置顶记录。</p>
      {resetCategories.map((item) => <label key={item.id} className="flex items-center gap-2 text-[11px]"><input type="checkbox" checked={selected.includes(item.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /><span className="flex-1">{item.label} · {item.file_count} 项</span><span>{formatBytes(item.bytes)}{item.preserved ? '（会话仅归档项）' : ''}</span></label>)}
      <div className="flex flex-wrap items-center gap-2"><button type="button" onClick={() => void previewReset()} className="rounded border border-line px-2 py-1 text-[11px]">刷新重置预览</button><button type="button" disabled={!selected.length} onClick={() => void applyReset()} className="rounded border border-line px-2 py-1 text-[11px] disabled:opacity-40">清理所选资源</button><span role="status" className="text-[11px] text-fg-3">估算上限 {formatBytes(totalSelected)} · {resetMessage}</span></div>
    </section>
  </div>;
}
