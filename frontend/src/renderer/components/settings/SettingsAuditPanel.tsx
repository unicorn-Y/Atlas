import { useEffect, useState } from 'react';
import { api } from '../../services/api';

interface Privacy { telemetry_enabled: boolean; crash_capture_enabled: boolean; crash_upload_enabled: false; telemetry_senders: string[] }
interface SettingKey { key: string; status: 'partial' | 'unsupported'; equivalent: string; consumer: string }
interface Catalog { official_source: string; retrieved: string; keys: SettingKey[]; sources: Array<{ source: string; state: string; keys: string[] }>; environment_overrides: Array<{ key: string; present: boolean }>; precedence_note: string }
interface Resource { supported: boolean; backend_rss_bytes?: number; backend_threads?: number | null; system_memory_percent?: number; system_cpu_percent?: number | null; reason?: string }
interface HttpSample { transport: string; status_code: number | null; duration_ms: number; retries: number; recorded_at: string }
interface HttpSummary { http_observed: boolean; samples: HttpSample[]; usage_last_7_days: { input_tokens: number; output_tokens: number; runs: number } | null; scope: string }

/** The desktop owns raw crash files. It exposes only counts and an explicit local export action. */
export interface LocalCrashCapture {
  apply: (enabled: boolean) => Promise<{ enabled: boolean; restartRequired?: boolean }>;
  status: () => Promise<{ enabled: boolean; count: number; reports?: Array<{ id: string; size: number; modifiedAt: string }> }>;
  export: (reportId: string) => Promise<{ exported: boolean }>;
}

export default function SettingsAuditPanel({ apiBaseUrl, desktopCrashCapture }: { apiBaseUrl: string; desktopCrashCapture?: LocalCrashCapture }) {
  const [privacy, setPrivacy] = useState<Privacy | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [resource, setResource] = useState<Resource | null>(null);
  const [http, setHttp] = useState<HttpSummary | null>(null);
  const [query, setQuery] = useState('');
  const [supportedOnly, setSupportedOnly] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [crash, setCrash] = useState<{ enabled: boolean; count: number; reports?: Array<{ id: string; size: number; modifiedAt: string }> } | null>(null);

  const refresh = async () => {
    setBusy(true); setError('');
    const results = await Promise.allSettled([
      api<Privacy>(apiBaseUrl, '/api/settings-audit/privacy'),
      api<Catalog>(apiBaseUrl, '/api/settings-audit/catalog'),
      api<Resource>(apiBaseUrl, '/api/settings-audit/resources'),
      api<HttpSummary>(apiBaseUrl, '/api/settings-audit/model-http'),
    ]);
    if (results[0].status === 'fulfilled') setPrivacy(results[0].value);
    if (results[1].status === 'fulfilled') setCatalog(results[1].value);
    if (results[2].status === 'fulfilled') setResource(results[2].value);
    if (results[3].status === 'fulfilled') setHttp(results[3].value);
    const failures = results.filter((item) => item.status === 'rejected');
    if (failures.length) setError(`有 ${failures.length} 项读取失败，请刷新重试。`);
    if (desktopCrashCapture) {
      try { setCrash(await desktopCrashCapture.status()); }
      catch { setError('桌面崩溃收集状态读取失败。'); }
    }
    setBusy(false);
  };
  useEffect(() => { void refresh(); }, [apiBaseUrl, desktopCrashCapture]);

  const save = async (patch: Partial<Pick<Privacy, 'telemetry_enabled' | 'crash_capture_enabled'>>) => {
    if (!privacy) return;
    setBusy(true); setError(''); setNotice('');
    const next = { telemetry_enabled: privacy.telemetry_enabled, crash_capture_enabled: privacy.crash_capture_enabled, ...patch };
    try {
      const saved = await api<Privacy>(apiBaseUrl, '/api/settings-audit/privacy', { method: 'PUT', json: next });
      setPrivacy(saved);
      if (desktopCrashCapture && patch.crash_capture_enabled !== undefined) {
        const applied = await desktopCrashCapture.apply(saved.crash_capture_enabled);
        if (!applied.restartRequired && applied.enabled !== saved.crash_capture_enabled) throw new Error('Desktop state mismatch');
        setCrash(await desktopCrashCapture.status());
        setNotice(applied.restartRequired ? '偏好已保存，重启 Atlas 后生效。' : '本机崩溃收集设置已应用。');
      } else setNotice('设置已保存并应用到现有遥测 sender。');
    } catch { setError('设置未完全应用；请刷新核对已保存偏好与桌面实际状态。'); }
    finally { setBusy(false); }
  };

  const exportCrash = async (reportId: string) => {
    if (!desktopCrashCapture) return;
    setBusy(true); setError('');
    try { const result = await desktopCrashCapture.export(reportId); setNotice(result.exported ? '已导出到你选择的本机目录。' : '已取消导出。'); }
    catch { setError('本机崩溃导出失败。'); }
    finally { setBusy(false); }
  };
  const exportSummary = () => {
    const blob = new Blob([JSON.stringify({ catalog, resource, http }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = 'atlas-settings-diagnostics.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const keys = catalog?.keys.filter((item) => (!supportedOnly || item.status === 'partial') && `${item.key} ${item.equivalent}`.toLowerCase().includes(query.toLowerCase())) ?? [];
  const button = 'rounded-lg border border-line px-3 py-1.5 text-[12px] disabled:opacity-50';
  return <div className="grid max-w-[900px] gap-6 text-[13px] text-fg-2">
    <div className="flex gap-2"><button className={button} disabled={busy} onClick={() => void refresh()}>刷新诊断</button><button className={button} disabled={!catalog} onClick={exportSummary}>导出脱敏摘要</button></div>
    {error && <p role="alert" className="text-danger">{error}</p>}{notice && <p role="status">{notice}</p>}
    <section className="grid gap-3"><h4 className="m-0 text-heading">隐私与本机崩溃收集</h4>
      <p className="m-0 text-fg-3">遥测开关管理 Atlas 已登记的 sender。崩溃文件仅在本机收集，默认关闭，永不自动上传。</p>
      {privacy && <>
        <label className="flex gap-2"><input type="checkbox" checked={privacy.telemetry_enabled} disabled={busy} onChange={(event) => void save({ telemetry_enabled: event.target.checked })} />允许使用情况遥测（{privacy.telemetry_senders.join('、')}）</label>
        <label className="flex gap-2"><input type="checkbox" checked={privacy.crash_capture_enabled} disabled={busy || !desktopCrashCapture} onChange={(event) => void save({ crash_capture_enabled: event.target.checked })} />允许本机崩溃收集</label>
        {!desktopCrashCapture ? <p className="m-0 text-fg-3">当前客户端未提供本机崩溃收集接口。</p> : <><p className="m-0 text-fg-3">桌面实际状态：{crash ? crash.enabled ? '已开启' : '已关闭' : '未读取'}；已收集 {crash?.count ?? 0} 份。导出可能包含进程内存，请自行决定是否分享。</p>
          {!!crash?.reports?.length && <div className="grid gap-2">{crash.reports.map((report) => <div key={report.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-sunken px-3 py-2"><span className="text-[12px]">{new Date(report.modifiedAt).toLocaleString()} · {(report.size / 1048576).toFixed(1)} MB</span><button className={button} disabled={busy} onClick={() => void exportCrash(report.id)}>导出此报告</button></div>)}</div>}
          {!crash?.reports?.length && <p className="m-0 text-fg-3">没有本机崩溃报告。</p>}
        </>}
      </>}
    </section>
    <section className="grid gap-3"><h4 className="m-0 text-heading">配置来源</h4><p className="m-0 text-fg-3">{catalog?.precedence_note}</p>
      {catalog?.sources.map((source) => <details key={source.source}><summary>{source.source}：{source.state}，{source.keys.length} 个键（值已隐藏）</summary><div className="mt-2 max-h-40 overflow-auto font-mono text-[12px]">{source.keys.map((key) => <div key={key}>{key}</div>)}</div></details>)}
      {catalog?.environment_overrides.map((item) => <p key={item.key} className="m-0 font-mono text-[12px]">{item.key}：{item.present ? '存在环境覆盖（值隐藏）' : '未设置'}</p>)}
    </section>
    <section className="grid gap-3"><h4 className="m-0 text-heading">Claude 官方设置键映射</h4>
      <p className="m-0 text-fg-3">官方清单 {catalog?.keys.length ?? 0} 项，读取日期 {catalog?.retrieved}。部分对应表示 Atlas 使用自己的设置合同；这里不会自动导入或执行 Claude 配置。</p>
      {catalog && <a className="text-brand" href={catalog.official_source} target="_blank" rel="noreferrer">官方设置参考</a>}
      <input type="search" aria-label="搜索设置键" className="rounded-lg border border-line bg-surface px-3 py-2" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索设置键或 Atlas 对应功能" />
      <label><input type="checkbox" checked={supportedOnly} onChange={(event) => setSupportedOnly(event.target.checked)} />只看已有部分对应</label>
      <div className="max-h-80 overflow-auto"><table className="w-full text-left"><thead><tr><th>官方键</th><th>支持范围</th><th>Atlas 对应</th></tr></thead><tbody>{keys.map((item) => <tr key={item.key} className="border-t border-line"><td className="p-2 font-mono text-[11px]">{item.key}</td><td className="p-2">{item.status === 'partial' ? '部分对应' : '不支持'}</td><td className="p-2">{item.equivalent}{item.consumer && <small className="block text-fg-3">{item.consumer}</small>}</td></tr>)}</tbody></table></div>
    </section>
    <section className="grid gap-3"><h4 className="m-0 text-heading">本机资源</h4>{resource?.supported ? <p className="m-0">后端内存 {Math.round((resource.backend_rss_bytes ?? 0) / 1048576)} MB · 线程 {resource.backend_threads ?? '不可用'} · 系统内存 {resource.system_memory_percent}% · 系统 CPU {resource.system_cpu_percent == null ? '不可用' : `${resource.system_cpu_percent}%（距上次读取采样）`}</p> : <p className="m-0 text-fg-3">{resource?.reason ?? '正在读取'}</p>}</section>
    <section className="grid gap-3"><h4 className="m-0 text-heading">模型 HTTP 摘要</h4><p className="m-0 text-fg-3">{http?.scope} 仅保存 transport、状态码、耗时与重试数，不收集 URL、Header、正文或错误内容。</p>
      {!http?.http_observed && <p className="m-0">当前没有可用 HTTP 样本。</p>}
      {http?.usage_last_7_days && <p className="m-0">近七天 {http.usage_last_7_days.runs} 轮；输入 {http.usage_last_7_days.input_tokens}、输出 {http.usage_last_7_days.output_tokens} token。</p>}
      {!!http?.samples.length && <div className="max-h-52 overflow-auto"><table className="w-full text-left"><thead><tr><th>传输</th><th>HTTP</th><th>耗时 ms</th><th>重试</th></tr></thead><tbody>{[...http.samples].reverse().map((row, index) => <tr key={`${row.recorded_at}-${index}`}><td>{row.transport}</td><td>{row.status_code ?? '未返回状态码'}</td><td>{row.duration_ms}</td><td>{row.retries}</td></tr>)}</tbody></table></div>}
    </section>
  </div>;
}
