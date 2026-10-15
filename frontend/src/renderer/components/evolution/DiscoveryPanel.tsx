// 全网发现：各家更新日志、GitHub、HN、Reddit、MCP 注册表、技能市场、论坛和网页搜索里
// 新出的 agent / 功能 / 工具，判断值不值得吸收，产出报告和移植任务书草稿（core/atlas/evolution/discovery）。
import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, FileText, Globe2, LoaderCircle, Play } from 'lucide-react';
import { api, relativeTime } from '../../services/api';
import MarkdownContent from '../MarkdownContent';
import Section from './Section';

type Row = { id: string; title: string; url: string; source: string; verdict: string; feature?: string; atlas_gap?: string; port_from?: string; effort?: string; value?: number };
type Status = {
  running: boolean; last_run_at: string | null; last_report: string | null; reports: string[]; error: string | null;
  last_counts: { collected: number; judged: number; absorb: number; drafts: number } | null;
  last_errors: Record<string, string> | null; settings: { enabled: boolean; interval_hours: number; days: number };
};

export default function DiscoveryPanel({ apiBaseUrl, onToast, onDraftsChanged }: { apiBaseUrl: string; onToast?: (text: string) => void; onDraftsChanged?: () => void }) {
  const [open, setOpen] = useState(true);
  const [status, setStatus] = useState<Status | null>(null);
  const [report, setReport] = useState<{ name: string; markdown: string; rows: Row[] } | null>(null);
  const [showFull, setShowFull] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const next = await api<Status>(apiBaseUrl, '/api/evolution/discovery');
      setStatus((previous) => {
        if (previous?.running && !next.running) onDraftsChanged?.();
        return next;
      });
      setError('');
      if (next.last_report) setReport(await api(apiBaseUrl, `/api/evolution/discovery/reports/${next.last_report}`));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '读不到全网发现的状态'); }
  }, [apiBaseUrl, onDraftsChanged]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!status?.running) return undefined;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [status?.running, load]);

  const run = async () => {
    try {
      const result = await api<Status & { started: boolean }>(apiBaseUrl, '/api/evolution/discovery/run', { method: 'POST', json: {} });
      setStatus(result);
      onToast?.(result.started ? '开始全网发现，几分钟后出报告' : '已经在跑了');
    } catch (cause) { onToast?.(cause instanceof Error ? cause.message : '没能开始'); }
  };

  const absorb = report?.rows.filter((row) => row.verdict === 'absorb') ?? [];
  const counts = status?.last_counts;
  return <Section icon={Globe2} title="全网发现" count={absorb.length} open={open} onToggle={() => setOpen(!open)}
    hint={status?.settings.enabled ? `每 ${status.settings.interval_hours} 小时自动跑一次` : '自动运行已关闭'}
    error={error} onRetry={() => void load()} onDismissError={() => setError('')}
    controls={<button className="btn ghost" disabled={status?.running} onClick={() => void run()}>
      {status?.running ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}{status?.running ? '正在发现…' : '现在跑一次'}
    </button>}>
    <div className="grid min-w-0 gap-2 px-3.5 pb-3 text-[12.5px] [overflow-wrap:anywhere]">
      <div className="text-fg-3">
        {status?.last_run_at ? `上次：${relativeTime(status.last_run_at)}` : '还没跑过'}
        {counts && ` · 抓到 ${counts.collected} 条，判断 ${counts.judged} 条，值得吸收 ${counts.absorb} 条，生成任务书草稿 ${counts.drafts} 份`}
        {status?.error && <span className="text-danger"> · 上次出错：{status.error}</span>}
      </div>
      {status?.last_errors && Object.keys(status.last_errors).length > 0 && <div className="text-fg-3">
        这些源这次没读到：{Object.keys(status.last_errors).join('、')}
      </div>}
      {absorb.map((row) => <div key={row.id} className="min-w-0 rounded-lg bg-sunken px-3 py-2 [overflow-wrap:anywhere]">
        <div className="flex items-start gap-2">
          <span className="min-w-0 flex-1 font-medium text-fg">{row.feature || row.title}</span>
          <a href={row.url} target="_blank" rel="noreferrer" className="inline-flex max-w-[40%] shrink-0 truncate items-center gap-1 text-fg-3 hover:text-fg">{row.source}<ExternalLink size={11} /></a>
        </div>
        {row.atlas_gap && <div className="mt-1 text-fg-2">Atlas：{row.atlas_gap}</div>}
        {row.port_from && <div className="mt-0.5 text-fg-3">移植：{row.port_from} · 工作量 {row.effort ?? 'M'} · 价值 {row.value ?? 3}/5</div>}
      </div>)}
      {report && <button className="inline-flex w-fit items-center gap-1 text-fg-2 hover:text-fg" onClick={() => setShowFull(!showFull)}>
        <FileText size={13} />{showFull ? '收起完整报告' : `看完整报告（${report.name}）`}
      </button>}
      {showFull && report && <div className="max-h-[480px] overflow-auto rounded-lg px-3 py-2 shadow-[inset_0_0_0_1px_var(--line)]"><MarkdownContent content={report.markdown} /></div>}
    </div>
  </Section>;
}
