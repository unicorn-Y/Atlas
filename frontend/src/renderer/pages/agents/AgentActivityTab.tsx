import { useCallback, useEffect, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { agentsApi, automationsApi, type AutomationRun } from '../../services/persistentApi';
import { useAtlasStore } from '../../store/useAtlasStore';
import { relativeTime } from '../../services/api';
import { describeAutomation } from '../automations/describe';
import { StatusBadge } from './shared';
import type { PersistentAgentRecord } from '../../services/persistentApi';

interface ActivityRow { at: string; text: string; detail?: string }
const RUN_LABEL: Record<string, string> = {
  completed: '完成', failed: '失败', running: '运行中', cancelled: '已停止', error: '出错',
};

/** Activity：状态投影（当前/最后活动/最后错误）+ 该 Agent 名下自动化的运行历史。 */
export default function AgentActivityTab({ apiBaseUrl, agent }: { apiBaseUrl: string; agent: PersistentAgentRecord }) {
  const automations = useAtlasStore((state) => state.automations);
  const loadAutomations = useAtlasStore((state) => state.loadAutomations);
  const [statusError, setStatusError] = useState('');
  const [runs, setRuns] = useState<Record<string, AutomationRun[]>>({});
  const [loading, setLoading] = useState(true);
  const base = apiBaseUrl;
  const agentId = agent.id;

  useEffect(() => { void loadAutomations(); }, [loadAutomations]);

  const mine = automations.filter((item) => item.owner_agent_id === agentId || (item.payload?.kind === 'heartbeat' && item.payload?.agent_id === agentId));
  const mineRef = useRef(mine);
  mineRef.current = mine;

  const reload = useCallback(async () => {
    setLoading(true);
    try { setStatusError((await agentsApi.status(base, agentId)).error || ''); } catch { /* 状态读不到就用列表兜底 */ }
    const next: Record<string, AutomationRun[]> = {};
    await Promise.all(mineRef.current.map(async (item) => {
      next[item.id] = await automationsApi.runs(base, item.id, 10).then((body) => body.runs).catch(() => []);
    }));
    setRuns(next);
    setLoading(false);
  }, [base, agentId]);
  useEffect(() => { void reload(); }, [reload, automations.length]);

  const rows: ActivityRow[] = [
    ...(agent.agent?.last_activity_at ? [{ at: agent.agent.last_activity_at, text: '最后活动', detail: `状态 ${agent.status ?? 'unknown'}` }] : []),
    ...(statusError ? [{ at: agent.agent?.last_activity_at ?? '', text: '错误', detail: statusError }] : []),
    ...mine.flatMap((item) => (runs[item.id] ?? []).map((run) => ({
      at: String(run.started_at ?? ''),
      text: `运行 ${item.name}`,
      detail: `${RUN_LABEL[String(run.status ?? '')] ?? String(run.status ?? 'unknown')}${run.workflow_run_id ? ` · ${String(run.workflow_run_id)}` : ''}`,
    }))),
  ].sort((a, b) => (b.at || '').localeCompare(a.at || ''));

  return <div className="grid max-w-[680px] gap-4">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl bg-sunken px-4 py-3 text-[12.5px] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">
      <StatusBadge status={agent.status} />
      <span>最后活动：{agent.agent?.last_activity_at ? relativeTime(agent.agent.last_activity_at) : '还没有'}</span>
      {agent.agent?.last_error && <span className="w-full text-danger">上次出错：{agent.agent.last_error}</span>}
    </div>
    <div aria-label="活动时间线" className="grid gap-1">
      {rows.map((row, index) => <p key={index} className="m-0 flex items-baseline gap-2.5 border-b border-line py-1.5 text-[13px] last:border-0">
        <span className="w-20 shrink-0 text-right text-[11.5px] tabular-nums text-fg-3">{relativeTime(row.at) || '—'}</span>
        <b className="shrink-0 font-medium text-fg-2">{row.text}</b>
        <span className="min-w-0 flex-1 truncate text-fg-3">{row.detail}</span>
      </p>)}
      {!rows.length && <div className="empty py-10"><LoaderCircle size={20} className={loading ? 'spin' : 'hidden'} /><b>{loading ? '正在读取活动…' : '还没有活动'}</b>聊一句、跑一次心跳或自动化，这里就会有记录。</div>}
    </div>
    {mine.length > 0 && <details>
      <summary className="cursor-pointer select-none px-1 text-[12.5px] text-fg-3 hover:text-fg-2">它名下的自动化（{mine.length} 条）</summary>
      <div className="mt-2 grid gap-1.5">
        {mine.map((item) => <p key={item.id} className="m-0 rounded-lg bg-sunken px-3 py-2 text-[12.5px] text-fg-2">{item.name} · {describeAutomation(item)}</p>)}
      </div>
    </details>}
  </div>;
}
