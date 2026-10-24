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
  const blob = new Blob([`${JSON.stringify(report, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `atlas-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
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
      <button className={styles.settingsActionSecondary} type="button" disabled={loading} onClick={() => void refresh()}>
        {loading ? '检查中…' : '刷新检查'}
      </button>
    </div>
    <p>诊断报告只读取本机后端状态和配置文件格式，不上传报告。密钥、令牌、配置内容和本机路径不会写入报告。单独点击模型连通性测试时，会向当前模型发送一条短测试请求。</p>
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
        <button className={styles.settingsActionSecondary} type="button" onClick={() => saveReport(report)}>导出 JSON</button>
      </div>
      {modelProbe && <p role={modelProbe.ok ? 'status' : 'alert'} className={modelProbe.ok ? styles.settingsSuccess : styles.settingsError}>{modelProbe.ok ? '模型连通性通过。' : `模型连通性失败：${modelProbe.message}`}</p>}
      <label>可复制的诊断报告
        <textarea readOnly rows={10} value={JSON.stringify(report, null, 2)} onFocus={(event) => event.currentTarget.select()} />
      </label>
    </div>}
  </section><DiagnosticsHub apiBaseUrl={apiBaseUrl} workspacePath={workspacePath} /> </>;
}
