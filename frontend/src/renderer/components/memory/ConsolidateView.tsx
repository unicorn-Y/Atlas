import { useCallback, useEffect, useState } from 'react';
import { Check, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react';
import { api } from '../../services/api';

/**
 * 语义候选 —— the review surface for consolidation.
 *
 * Consolidation reads recent episodes and diary entries and proposes semantic
 * statements, each backed by a verbatim quote from something the user actually
 * said. Nothing is written to the memory library until the user applies it here.
 *
 * Two deliberate behaviours, both matching the backend:
 *  - 提出 (propose) needs a model and only rewrites 语义候选.md; it never touches
 *    memory. It is the expensive, optional step.
 *  - 采纳 (apply) needs no model and is what actually writes: it appends entries,
 *    lowers the importance of what they replace, and records the supersession.
 *    It never deletes anything, so applying is safe to try.
 */

type Source = { id: string; path: string; date: string; at: string; who: string; quote: string };
type Candidate = {
  id: string;
  key: string;
  text: string;
  value: string;
  quote: string;
  importance: number;
  reason: string;
  evidence: string;
  kind: 'single' | 'recurring';
  sources: Source[];
};

type Pending = {
  exists: boolean;
  path: string;
  pending: Candidate[];
  pending_count: number;
  applied_count: number;
  skipped_count: number;
};

type Props = {
  apiBaseUrl: string;
  connected: boolean;
  onToast: (text: string) => void;
};

export default function ConsolidateView({ apiBaseUrl, connected, onToast }: Props) {
  const [data, setData] = useState<Pending | null>(null);
  const [busy, setBusy] = useState<'load' | 'propose' | 'apply' | null>(null);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy('load');
    setError('');
    try {
      setData(await api<Pending>(apiBaseUrl, '/api/memlib/consolidate'));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(null);
    }
  }, [apiBaseUrl]);

  useEffect(() => { if (connected) void load(); }, [connected, load]);

  const propose = async () => {
    setBusy('propose');
    setError('');
    try {
      const result = await api<{ ok: boolean; candidates?: number; sources?: number; error?: string | null }>(
        apiBaseUrl, '/api/memlib/consolidate',
        { method: 'POST', json: { apply: false } },
      );
      if (result.error) onToast(result.error);
      else if (!result.candidates) onToast(`看了 ${result.sources ?? 0} 条原文，没有新的可整理内容`);
      else onToast(`整理出 ${result.candidates} 条，等你确认`);
      await load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    setBusy('apply');
    setError('');
    try {
      const result = await api<{ ok: boolean; added?: number; lowered?: number; superseded?: number; error?: string | null }>(
        apiBaseUrl, '/api/memlib/consolidate',
        { method: 'POST', json: { apply: true } },
      );
      if (result.error) onToast(result.error);
      else if (!result.added) onToast('没有可采纳的候选');
      else onToast(`已并入 ${result.added} 条${result.lowered ? `，${result.lowered} 条旧说法降了优先级` : ''}`);
      await load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(null);
    }
  };

  const pending = data?.pending ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-[var(--line)] px-4 py-3 lg:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles size={16} className="text-[var(--brand)]" />
          <b className="text-sm">待确认的整理</b>
          <span className="rounded-full bg-[var(--sunken)] px-2 py-0.5 text-[11px] text-fg-2">
            {pending.length} 条待确认
          </span>
          {data && data.applied_count > 0 ? (
            <span className="text-[11px] text-fg-3">已并入 {data.applied_count}</span>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-2.5 py-1.5 text-xs text-fg-2 hover:bg-[var(--panel)] disabled:opacity-50"
              onClick={() => void propose()}
              disabled={!connected || busy !== null}
              title="读最近两周的经历和你说过的话，提出可整理的语义（需要模型，只写候选文件，不动记忆）"
            >
              {busy === 'propose' ? <LoaderCircle size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              整理一次
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--brand)] px-2.5 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              onClick={() => void apply()}
              disabled={!connected || busy !== null || pending.length === 0}
              title="把上面的候选并入记忆：只追加，冲突的旧说法只降优先级，不删除任何东西"
            >
              {busy === 'apply' ? <LoaderCircle size={13} className="animate-spin" /> : <Check size={13} />}
              全部采纳
            </button>
          </div>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-fg-3">
          每条都带着你的原话和出处；看过没问题再采纳。采纳只往文件里追加，遇到和旧说法冲突的只会降低旧条目的优先级，<b className="text-fg-2">不会删除</b>。
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 lg:px-6">
        {error ? (
          <div className="rounded-lg border border-[var(--danger)] bg-[var(--danger-soft)] px-3 py-2 text-xs text-[var(--danger)]">
            {error}
            <button type="button" className="ml-2 underline" onClick={() => void load()}>重试</button>
          </div>
        ) : null}

        {busy === 'load' && !data ? (
          <div className="flex items-center gap-2 py-8 text-sm text-fg-3">
            <LoaderCircle size={15} className="animate-spin" /> 正在读候选……
          </div>
        ) : null}

        {!busy && data && pending.length === 0 ? (
          <div className="py-10 text-center text-sm text-fg-3">
            <p>暂时没有新候选。</p>
            <p className="mt-1 text-xs">点「整理一次」让它读一下最近的经历，看有什么值得记下来的。</p>
          </div>
        ) : null}

        <ul className="space-y-2">
          {pending.map((candidate) => {
            const open = expanded === candidate.id;
            return (
              <li key={candidate.id} className="rounded-lg border border-[var(--line)] bg-[var(--panel)]">
                <button
                  type="button"
                  className="flex w-full items-start gap-2 px-3 py-2.5 text-left"
                  onClick={() => setExpanded(open ? null : candidate.id)}
                >
                  <span className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] ${candidate.kind === 'recurring' ? 'bg-[var(--ok-soft)] text-[var(--ok)]' : 'bg-[var(--sunken)] text-fg-2'}`}>
                    {candidate.kind === 'recurring' ? '多次说过' : '只说过一次'}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-fg-1">{candidate.text}</span>
                    <span className="mt-0.5 block truncate text-[11px] text-fg-3">
                      {candidate.key} · 重要度 {candidate.importance} · {candidate.evidence}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] text-fg-3">{open ? '收起' : '看原文'}</span>
                </button>
                {open ? (
                  <div className="border-t border-[var(--line)] px-3 py-2">
                    {candidate.reason ? <p className="mb-1.5 text-[11px] text-fg-2">{candidate.reason}</p> : null}
                    <ul className="space-y-1.5">
                      {candidate.sources.map((source) => (
                        <li key={`${candidate.id}-${source.id}`} className="text-[11px] leading-relaxed text-fg-2">
                          <span className="mr-1 shrink-0 rounded bg-[var(--sunken)] px-1.5 py-0.5 text-[10px] text-fg-3">
                            {source.who} · {source.date}
                          </span>
                          <q className="text-fg-1">{source.quote || '（见原文）'}</q>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>

        {data && !data.exists ? (
          <p className="mt-4 text-[11px] text-fg-3">
            还没有 {data.path.split(/[\\/]/).pop()}，点「整理一次」会生成它。
          </p>
        ) : null}
      </div>
    </div>
  );
}
