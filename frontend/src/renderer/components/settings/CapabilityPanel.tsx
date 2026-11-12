import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';

/**
 * Capability health: "what can Atlas actually do right now?"
 *
 * `/api/health` only answers "did startup finish?" — a component can be `ready`
 * while the thing it wraps is unusable (an MCP server whose process died, a
 * memory index that is stale, a model whose key was rotated). This panel asks
 * `/api/capabilities`, which runs one real check per capability and reports the
 * failures with a remediation hint.
 *
 * The chat-model check costs a tiny real model request, so the server caches its
 * verdict for ten minutes and this panel never retests the model implicitly: a
 * plain refresh re-runs only the local probes, and "重新测一次模型" is an explicit
 * button because it spends tokens.
 */

type Probe = {
  id: string;
  title: string;
  status: 'ok' | 'degraded' | 'unavailable';
  detail: string;
  remediation: string;
  latency_ms: number;
};

type Report = {
  status: 'ok' | 'degraded' | 'unavailable';
  duration_ms: number;
  cached?: boolean;
  summary: { total: number; ok: number; degraded: number; unavailable: number };
  probes: Probe[];
  failing: Probe[];
};

const TONE: Record<string, string> = {
  ok: 'bg-[var(--ok-soft)] text-[var(--ok)]',
  degraded: 'bg-[var(--warn-soft,#fef3c7)] text-[var(--warn,#b45309)]',
  unavailable: 'bg-[var(--danger-soft)] text-[var(--danger)]',
};

const LABEL: Record<string, string> = { ok: '正常', degraded: '降级', unavailable: '不可用' };

export default function CapabilityPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (options: { recheckModel?: boolean } = {}) => {
    setBusy(true);
    setError('');
    try {
      const query = options.recheckModel ? '?refresh=true&recheck_model=true' : '?refresh=true';
      setReport(await api<Report>(apiBaseUrl, `/api/capabilities${query}`));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-[12px]">能力体检</strong>
        {report ? (
          <span className={`rounded-full px-2 py-0.5 text-[11px] ${TONE[report.status] ?? 'bg-sunken text-fg-3'}`}>
            {LABEL[report.status] ?? report.status} · {report.summary.ok}/{report.summary.total}
          </span>
        ) : null}
        {report ? <span className="text-[10.5px] text-fg-3">耗时 {report.duration_ms} ms{report.cached ? ' · 来自缓存' : ''}</span> : null}
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={busy}
            className="rounded border border-line px-2.5 py-1 text-[11px] disabled:opacity-50"
            title="重新检查本机各项能力（不花模型额度）"
          >
            {busy ? '检查中…' : '重新检查'}
          </button>
          <button
            type="button"
            onClick={() => void load({ recheckModel: true })}
            disabled={busy}
            className="rounded border border-line px-2.5 py-1 text-[11px] text-fg-2 disabled:opacity-50"
            title="顺便重新向模型问一句 OK，会消耗一次极小的真实请求"
          >
            重新测一次模型
          </button>
        </div>
      </div>
      <p className="m-0 text-[11px] text-fg-3">
        每项都是真跑一次，不是看启动状态。模型那项十分钟内复用上次结论，所以点「重新检查」不会花钱。
      </p>
      {error ? <p role="alert" className="m-0 text-[11.5px] text-danger">读取能力状态失败：{error}</p> : null}
      {report?.failing.length ? (
        <ul className="grid gap-1.5">
          {report.failing.map((probe) => (
            <li key={probe.id} className="rounded-lg bg-sunken p-2 text-[11.5px]">
              <div className="flex items-center gap-2">
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${TONE[probe.status]}`}>{LABEL[probe.status] ?? probe.status}</span>
                <strong className="text-fg-1">{probe.title}</strong>
                <span className="ml-auto text-[10px] text-fg-3">{probe.latency_ms} ms</span>
              </div>
              <p className="my-1 break-words text-fg-2">{probe.detail}</p>
              {probe.remediation ? <p className="m-0 text-[11px] text-fg-3">怎么修：{probe.remediation}</p> : null}
            </li>
          ))}
        </ul>
      ) : report ? (
        <p className="m-0 text-[11.5px] text-[var(--ok)]">全部能力都正常，没有需要处理的问题。</p>
      ) : null}
      {report && !report.failing.length ? (
        <details className="rounded-lg bg-sunken p-2 text-[11px]">
          <summary className="cursor-pointer text-fg-2">展开看每项耗时（{report.probes.length} 项）</summary>
          <ul className="mt-1 grid gap-0.5">
            {report.probes.map((probe) => (
              <li key={probe.id} className="flex gap-2">
                <span className="w-24 shrink-0 text-fg-3">{probe.latency_ms} ms</span>
                <span className="min-w-0 flex-1 truncate text-fg-2">{probe.title}</span>
                <span className="shrink-0 text-fg-3">{probe.detail}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
