import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import styles from '../../App.module.css';

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
export default function DiagnosticsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

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

  return <section className={styles.settingsCard} aria-label="诊断报告">
    <div className={styles.settingsCardHeading}>
      <h2>本机诊断</h2>
      <button className={styles.settingsActionSecondary} type="button" disabled={loading} onClick={() => void refresh()}>
        {loading ? '检查中…' : '刷新检查'}
      </button>
    </div>
    <p>只读取本机后端状态和配置文件格式，不发送网络请求或上传报告。密钥、令牌、配置内容和本机路径不会写入诊断结果。</p>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {report && <div aria-live="polite">
      <p className={report.summary.status === 'ok' ? styles.settingsSuccess : styles.settingsStatus} role="status">
        检查于 {new Date(report.generated_at).toLocaleString()} · {report.summary.check_count} 项，{report.summary.warning_count} 个提示，{report.summary.error_count} 个错误
      </p>
      <ul>
        {report.checks.map((check) => <li key={check.id}>
          <strong>{check.label}</strong>：{check.detail}
        </li>)}
      </ul>
      <div className="my-3 flex flex-wrap gap-2">
        <button className={styles.settingsActionSecondary} type="button" onClick={() => void copyReport()}>复制 JSON</button>
        <button className={styles.settingsActionSecondary} type="button" onClick={() => saveReport(report)}>导出 JSON</button>
      </div>
      <label>可复制的诊断报告
        <textarea readOnly rows={10} value={JSON.stringify(report, null, 2)} onFocus={(event) => event.currentTarget.select()} />
      </label>
    </div>}
  </section>;
}
