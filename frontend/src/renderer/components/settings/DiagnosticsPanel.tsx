import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import styles from '../../App.module.css';
import DiagnosticsHub from './DiagnosticsHub';

type DiagnosticCheck = {
  id: string;
  label: string;
  status: 'ok' | 'warning' | 'error' | 'unknown' | string;
  detail: string;
};

type DiagnosticReport = {
  schema_version: number;
  generated_at: string;
  summary: { status: string; check_count: number; warning_count: number; error_count: number };
  checks: DiagnosticCheck[];
  privacy: {
    local_only: boolean;
    network_requests: number;
    uploaded: boolean;
    secrets_included: boolean;
    paths_included: boolean;
  };
};

function saveReport(report: DiagnosticReport) {
  const bundle = {
    schema_version: 1,
    kind: 'atlas-local-bug-bundle',
    created_at: new Date().toISOString(),
    app: { user_agent: navigator.userAgent, locale: navigator.language },
    diagnostics: report,
    privacy: '本地生成；不含模型凭据、配置内容或本机路径；由用户选择是否分享。',
  };
  const blob = new Blob([`${JSON.stringify(bundle, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `atlas-bug-bundle-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

// Behavior reference: Claude Code's /doctor and /status diagnostics are local,
// user-inspectable status surfaces: https://code.claude.com/docs/en/commands
export default function DiagnosticsPanel({ apiBaseUrl, workspacePath = '' }: { apiBaseUrl: string; workspacePath?: string }) {
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [modelProbe, setModelProbe] = useState<{ ok: boolean; message: string } | null>(null);
  const [probingModel, setProbingModel] = useState(false);
  const [openingDashboard, setOpeningDashboard] = useState(false);
  const [safeMode, setSafeMode] = useState(false);
  const [rememberSafeMode, setRememberSafeMode] = useState(false);
  const [restartingSafeMode, setRestartingSafeMode] = useState(false);
  const [traceActive, setTraceActive] = useState(false);
  const [nativeAction, setNativeAction] = useState('');

  useEffect(() => {
    void Promise.all([window.atlasDesktop?.getSafeMode?.(), window.atlasDesktop?.getSafeModePreference?.()])
      .then(([active, preferred]) => { setSafeMode(active === true); setRememberSafeMode(preferred === true); }).catch(() => undefined);
  }, []);

  const setRemember = async (enabled: boolean) => {
    setRememberSafeMode(enabled);
    try { await window.atlasDesktop?.setSafeModePreference?.(enabled); }
    catch (reason) { setRememberSafeMode(!enabled); setError(reason instanceof Error ? reason.message : String(reason)); }
  };
  const restart = async (safe: boolean) => {
    setRestartingSafeMode(true); setError(null);
    try { await window.atlasDesktop?.restartBackend?.(safe); setSafeMode(safe); setRememberSafeMode(safe); setMessage(safe ? '正在以安全模式重启后端…' : '正在正常重启后端…'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setRestartingSafeMode(false); }
  };

  const refresh = async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      setReport(await api<DiagnosticReport>(apiBaseUrl, '/api/diagnostics'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setReport(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, [apiBaseUrl]);

  const copyReport = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
      setMessage('诊断报告已复制。');
    } catch {
      setMessage('无法访问剪贴板；可以选中下方报告文本并手动复制。');
    }
  };
  const probeModel = async () => {
    setProbingModel(true); setModelProbe(null);
    try { setModelProbe(await api(apiBaseUrl, '/api/settings/test-connection', { method: 'POST', json: {} })); }
    catch (reason) { setModelProbe({ ok: false, message: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setProbingModel(false); }
  };
  const openDashboard = async () => {
    setOpeningDashboard(true);
    setError(null);
    try {
      const access = await api<{ url: string }>(apiBaseUrl, '/api/dashboard/access', { method: 'POST', json: {} });
      const opened = await window.atlasDesktop?.openExternal?.(access.url);
      if (!opened) throw new Error('系统浏览器未能打开本地控制台网址。');
      setMessage('已在系统浏览器打开本地控制台。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setOpeningDashboard(false); }
  };
  const captureHeap = async () => {
    setError(null); setNativeAction('heap');
    try { const saved = await window.atlasDesktop?.captureHeapSnapshot?.(); setMessage(saved ? `Heap Snapshot 已保存：${saved}` : '已取消导出。'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setNativeAction(''); }
  };
  const toggleTrace = async () => {
    setError(null); setNativeAction('trace');
    try {
      if (!traceActive) { await window.atlasDesktop?.startPerformanceTrace?.(); setTraceActive(true); setMessage('性能追踪已开始；复现问题后停止并导出。'); }
      else { const saved = await window.atlasDesktop?.stopPerformanceTrace?.(); setTraceActive(false); setMessage(saved ? `性能追踪已保存：${saved}` : '性能追踪已停止，未保存文件。'); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setNativeAction(''); }
  };
  const advice = (check: DiagnosticCheck) => {
    if (check.status === 'ok') return '';
    if (check.id === 'backend') return '建议重启 Atlas 后端并查看启动日志。';
    if (check.id.startsWith('component:')) return '可在设置中重试对应组件；MCP 项请检查服务器配置和启动日志。';
    if (check.id.includes('config') || check.id === 'user_settings') return '先备份本机配置，再使用设置面板修复格式或恢复有效配置。';
    if (check.id === 'model_config') return '检查设置中的模型和凭据，然后运行模型连通性测试。';
    if (check.id === 'python_dependencies') return '在 Atlas 的 Python 环境中重新安装项目依赖。';
    if (check.id === 'disk_space') return '清理数据盘空间后重新启动 Atlas。';
    if (check.id === 'network_proxy') return '如果当前网络需要代理，请设置 HTTP(S)_PROXY 后重试。';
    return check.detail;
  };

  return <><section className={styles.settingsCard} aria-label="诊断报告">
    <div className={styles.settingsCardHeading}>
      <h2>本机诊断</h2>
      <div className="flex gap-2">
        <button className={styles.settingsActionSecondary} type="button" disabled={openingDashboard} onClick={() => void openDashboard()}>
          {openingDashboard ? '正在打开…' : '打开本地控制台'}
        </button>
        <button className={styles.settingsActionSecondary} type="button" disabled={loading} onClick={() => void refresh()}>
          {loading ? '检查中…' : '刷新检查'}
        </button>
      </div>
    </div>
    <p>诊断报告只读取本机后端状态和配置文件格式，不上传报告。密钥、令牌、配置内容和本机路径不会写入报告。单独点击模型连通性测试时，会向当前模型发送一条短测试请求。</p>
    <div className="my-3 grid gap-2 rounded-lg bg-sunken p-3" aria-label="安全模式控制">
      <p className="m-0 text-[12.5px]">后端当前{safeMode ? '以安全模式运行：跳过 MCP、市场技能、插件和扩展自动启动。' : '以正常模式运行。'}</p>
      <label className="flex items-center gap-2 text-[12.5px]"><input type="checkbox" checked={rememberSafeMode} onChange={(event) => void setRemember(event.target.checked)} />下次仍以安全模式启动</label>
      <button className={styles.settingsActionSecondary} type="button" disabled={restartingSafeMode} onClick={() => void restart(!safeMode)}>
        {restartingSafeMode ? '正在重启…' : safeMode ? '正常重启' : '以安全模式重启'}
      </button>
    </div>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {report && <div aria-live="polite">
      <p className={report.summary.status === 'ok' ? styles.settingsSuccess : styles.settingsStatus} role="status">
        检查于 {new Date(report.generated_at).toLocaleString()} · {report.summary.check_count} 项，{report.summary.warning_count} 个提示，{report.summary.error_count} 个错误
      </p>
      <ul>
        {report.checks.map((check) => <li key={check.id}>
          <strong>{check.label}</strong>：{check.detail}{advice(check) && <small className="block text-fg-3">建议：{advice(check)}</small>}
        </li>)}
      </ul>
      <div className="my-3 flex flex-wrap gap-2">
        <button className={styles.settingsActionSecondary} type="button" disabled={probingModel} onClick={() => void probeModel()}>{probingModel ? '测试模型连接中…' : '测试模型连通性'}</button>
        <button className={styles.settingsActionSecondary} type="button" onClick={() => void copyReport()}>复制 JSON</button>
        <button className={styles.settingsActionSecondary} type="button" onClick={() => saveReport(report)}>导出脱敏 Bug Bundle</button>
        <button className={styles.settingsActionSecondary} type="button" disabled={nativeAction !== ''} onClick={() => void captureHeap()}>{nativeAction === 'heap' ? '正在采集…' : '导出 Heap Snapshot'}</button>
        <button className={styles.settingsActionSecondary} type="button" disabled={nativeAction !== ''} onClick={() => void toggleTrace()}>{nativeAction === 'trace' ? '正在处理…' : traceActive ? '停止并导出性能追踪' : '开始性能追踪'}</button>
      </div>
      {modelProbe && <p role={modelProbe.ok ? 'status' : 'alert'} className={modelProbe.ok ? styles.settingsSuccess : styles.settingsError}>{modelProbe.ok ? '模型连通性通过。' : `模型连通性失败：${modelProbe.message}`}</p>}
      <label>可复制的诊断报告
        <textarea readOnly rows={10} value={JSON.stringify(report, null, 2)} onFocus={(event) => event.currentTarget.select()} />
      </label>
    </div>}
  </section><DiagnosticsHub apiBaseUrl={apiBaseUrl} workspacePath={workspacePath} /> </>;
}
