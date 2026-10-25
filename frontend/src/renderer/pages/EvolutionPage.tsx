import { useCallback, useEffect, useState } from 'react';
import {
  GitBranch, ListChecks, LoaderCircle, Pause, Play, RadioTower, RefreshCw, Scale, ScrollText, Sparkles, X,
} from 'lucide-react';
import {
  approveCandidate, rollbackCandidate, approveDraft, addEvolutionSource, generateDrafts, listBranches, listCandidates,
  listCuratorStatus, maintainCurator, pinCandidate, rejectCandidate, setCuratorPaused,
  listEvolutionDiffs, listEvolutionSources, listDrafts, listParityRows, removeEvolutionSource,
  runEvolutionCheck, type EvolutionBranch, type EvolutionCheckResult, type EvolutionDiff,
  type EvolutionDraft, type EvolutionSource, type EvolutionSourceKind, type ParityRow,
  type CuratorStatus, type SkillCandidate,
} from '../services/evolutionApi';
import Section from '../components/evolution/Section';
import SourceList from '../components/evolution/SourceList';
import DiffList from '../components/evolution/DiffList';
import ParitySuggestions from '../components/evolution/ParitySuggestions';
import DraftList from '../components/evolution/DraftList';
import BranchStatus from '../components/evolution/BranchStatus';
import SkillCandidates from '../components/evolution/SkillCandidates';
import { useAtlasStore } from '../store/useAtlasStore';
import UpstreamPanel from '../components/evolution/UpstreamPanel';

const errorText = (cause: unknown, fallback: string): string =>
  cause instanceof Error ? cause.message : fallback;

/** 侧栏「自动追新」主页面：上游监视 → 差异分类 → 对标建议 → 任务书草稿 → 隔离分支 → 技能候选。 */
export default function EvolutionPage({ apiBaseUrl, onToast }: {
  apiBaseUrl: string;
  onToast?: (message: string) => void;
}) {
  const [sources, setSources] = useState<EvolutionSource[]>([]);
  const [diffs, setDiffs] = useState<EvolutionDiff[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [parityRows, setParityRows] = useState<ParityRow[]>([]);
  const [patchProposal, setPatchProposal] = useState('');
  const [drafts, setDrafts] = useState<EvolutionDraft[]>([]);
  const [branches, setBranches] = useState<EvolutionBranch[]>([]);
  const [branchNote, setBranchNote] = useState('');
  const [candidates, setCandidates] = useState<SkillCandidate[]>([]);
  const [curatorStatus, setCuratorStatus] = useState<CuratorStatus | null>(null);
  const [curatorLoading, setCuratorLoading] = useState(true);
  const [curatorError, setCuratorError] = useState('');
  const [curatorBusy, setCuratorBusy] = useState(false);

  const [loading, setLoading] = useState({ sources: true, diffs: true, parity: true, drafts: true, branches: true, candidates: true });
  const [errors, setErrors] = useState({ sources: '', diffs: '', parity: '', drafts: '', branches: '', candidates: '' });
  const [open, setOpen] = useState({ sources: false, diffs: true, parity: false, drafts: true, branches: false, candidates: false });

  const [checkBusy, setCheckBusy] = useState(false);
  const [checkSummary, setCheckSummary] = useState<EvolutionCheckResult | null>(null);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [draftBusyId, setDraftBusyId] = useState('');
  const [generating, setGenerating] = useState(false);
  const [candidateBusyId, setCandidateBusyId] = useState('');

  const setSection = (key: keyof typeof loading, patch: { loading?: boolean; error?: string }) => {
    if (patch.loading !== undefined) setLoading((value) => ({ ...value, [key]: patch.loading! }));
    if (patch.error !== undefined) setErrors((value) => ({ ...value, [key]: patch.error! }));
  };

  const loadSources = useCallback(async () => {
    setSection('sources', { loading: true, error: '' });
    try {
      setSources(await listEvolutionSources(apiBaseUrl));
    } catch (cause) {
      setSection('sources', { error: errorText(cause, '监视来源暂时读不到，请稍后重试。') });
    } finally { setSection('sources', { loading: false }); }
  }, [apiBaseUrl]);

  const loadDiffs = useCallback(async () => {
    setSection('diffs', { loading: true, error: '' });
    try {
      const next = await listEvolutionDiffs(apiBaseUrl);
      setDiffs(next.diffs);
      setCounts(next.counts);
    } catch (cause) {
      setSection('diffs', { error: errorText(cause, '能力差异暂时读不到，请稍后重试。') });
    } finally { setSection('diffs', { loading: false }); }
  }, [apiBaseUrl]);

  const loadParity = useCallback(async () => {
    setSection('parity', { loading: true, error: '' });
    try {
      const next = await listParityRows(apiBaseUrl);
      setParityRows(next.rows);
      setPatchProposal(next.patch_proposal);
    } catch (cause) {
      setSection('parity', { error: errorText(cause, '对标建议暂时读不到，请稍后重试。') });
    } finally { setSection('parity', { loading: false }); }
  }, [apiBaseUrl]);

  const loadDrafts = useCallback(async () => {
    setSection('drafts', { loading: true, error: '' });
    try {
      setDrafts(await listDrafts(apiBaseUrl));
    } catch (cause) {
      setSection('drafts', { error: errorText(cause, '任务书草稿暂时读不到，请稍后重试。') });
    } finally { setSection('drafts', { loading: false }); }
  }, [apiBaseUrl]);

  const loadBranches = useCallback(async () => {
    setSection('branches', { loading: true, error: '' });
    try {
      const next = await listBranches(apiBaseUrl);
      setBranches(next.branches);
      setBranchNote(next.note);
    } catch (cause) {
      setSection('branches', { error: errorText(cause, '分支状态暂时读不到，请稍后重试。') });
    } finally { setSection('branches', { loading: false }); }
  }, [apiBaseUrl]);

  const loadCandidates = useCallback(async () => {
    setSection('candidates', { loading: true, error: '' });
    try {
      setCandidates(await listCandidates(apiBaseUrl));
    } catch (cause) {
      setSection('candidates', { error: errorText(cause, '技能候选暂时读不到，请稍后重试。') });
    } finally { setSection('candidates', { loading: false }); }
  }, [apiBaseUrl]);

  const loadCuratorStatus = useCallback(async () => {
    setCuratorLoading(true);
    setCuratorError('');
    try { setCuratorStatus(await listCuratorStatus(apiBaseUrl)); }
    catch (cause) { setCuratorError(errorText(cause, 'Curator 状态暂时读不到，请稍后重试。')); }
    finally { setCuratorLoading(false); }
  }, [apiBaseUrl]);

  useEffect(() => {
    void loadSources(); void loadDiffs(); void loadParity();
    void loadDrafts(); void loadBranches(); void loadCandidates(); void loadCuratorStatus();
  }, [loadSources, loadDiffs, loadParity, loadDrafts, loadBranches, loadCandidates, loadCuratorStatus]);

  const refreshAll = async () => {
    await Promise.all([loadSources(), loadDiffs(), loadParity(), loadDrafts(), loadBranches(), loadCandidates(), loadCuratorStatus()]);
    onToast?.('自动追新数据已刷新');
  };

  const checkNow = async () => {
    setCheckBusy(true);
    try {
      const result = await runEvolutionCheck(apiBaseUrl);
      setCheckSummary(result);
      const failed = result.errors.length ? `，${result.errors.length} 个来源读取失败` : '';
      onToast?.(`检查完成：${result.checked} 个来源，${result.new_commits} 条新动态${failed}`);
      await Promise.all([loadSources(), loadDiffs(), loadParity(), loadDrafts()]);
    } catch (cause) {
      onToast?.(errorText(cause, '检查没有跑完，请稍后再试。'));
    } finally { setCheckBusy(false); }
  };

  const addSource = async (source: { repo: string; kind: EvolutionSourceKind }) => {
    setSourceBusy(true);
    try {
      await addEvolutionSource(apiBaseUrl, source);
      onToast?.(`已添加来源 ${source.repo}`);
      await loadSources();
    } catch (cause) {
      onToast?.(errorText(cause, '来源没有添加成功，请检查仓库名后重试。'));
    } finally { setSourceBusy(false); }
  };

  const removeSource = async (id: string) => {
    setSourceBusy(true);
    try {
      await removeEvolutionSource(apiBaseUrl, id);
      onToast?.('来源已删除');
      await loadSources();
    } catch (cause) {
      onToast?.(errorText(cause, '来源没有删除成功，请稍后再试。'));
    } finally { setSourceBusy(false); }
  };

  const approve = async (draft: EvolutionDraft) => {
    setDraftBusyId(draft.id);
    try {
      const result = await approveDraft(apiBaseUrl, draft.id);
      if (result.ok && result.branch) onToast?.(`已创建隔离分支 ${result.branch}，合并前请在合并提案里确认`);
      else onToast?.(result.reason || '批准没有成功，草稿保持待批准。');
    } catch (cause) {
      onToast?.(errorText(cause, '批准没有成功，请稍后再试。'));
    } finally {
      setDraftBusyId('');
      await Promise.all([loadDrafts(), loadBranches()]);
    }
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const created = await generateDrafts(apiBaseUrl);
      onToast?.(created > 0 ? `已生成 ${created} 份任务书草稿` : '当前建议里没有需要写草稿的升级/替换项');
      await loadDrafts();
    } catch (cause) {
      onToast?.(errorText(cause, '草稿没有生成成功，请稍后再试。'));
    } finally { setGenerating(false); }
  };

  const approveCandidateSkill = async (candidate: SkillCandidate) => {
    setCandidateBusyId(candidate.id);
    try {
      await approveCandidate(apiBaseUrl, candidate.id);
      await useAtlasStore.getState().refreshSkills();
      onToast?.(`已批准「${candidate.title}」，技能包会交给技能库`);
    } catch (cause) {
      onToast?.(errorText(cause, '批准没有成功，请稍后再试。'));
    } finally {
      setCandidateBusyId('');
      await Promise.all([loadCandidates(), loadCuratorStatus()]);
    }
  };

  const maintainSkillCandidates = async () => {
    setCuratorBusy(true);
    try {
      const result = await maintainCurator(apiBaseUrl);
      onToast?.(`${result.note} 已检查 ${result.counts.checked ?? 0} 条，合并 ${result.counts.merged ?? 0} 条，标记过期 ${result.counts.flagged_outdated ?? 0} 条、闲置 ${result.counts.flagged_stale ?? 0} 条。`);
      await Promise.all([loadCandidates(), loadCuratorStatus()]);
    } catch (cause) { onToast?.(errorText(cause, 'Curator 整理失败，请稍后重试。')); }
    finally { setCuratorBusy(false); }
  };

  const toggleCuratorPause = async () => {
    if (!curatorStatus) return;
    setCuratorBusy(true);
    try {
      const paused = !curatorStatus.auto_maintenance_paused;
      await setCuratorPaused(apiBaseUrl, paused);
      onToast?.(paused ? '已暂停自动整理；仍可手动运行 Curator。' : '已恢复自动整理。');
      await loadCuratorStatus();
    } catch (cause) { onToast?.(errorText(cause, 'Curator 设置没有保存成功。')); }
    finally { setCuratorBusy(false); }
  };

  const pinSkillCandidate = async (candidate: SkillCandidate) => {
    setCandidateBusyId(candidate.id);
    try {
      await pinCandidate(apiBaseUrl, candidate.id, !candidate.pinned);
      onToast?.(candidate.pinned ? `已取消置顶「${candidate.title}」` : `已置顶「${candidate.title}」，自动整理会跳过此候选`);
    } catch (cause) { onToast?.(errorText(cause, '候选置顶状态没有保存成功。')); }
    finally { setCandidateBusyId(''); await Promise.all([loadCandidates(), loadCuratorStatus()]); }
  };

  const ignoreSkillCandidate = async (candidate: SkillCandidate) => {
    setCandidateBusyId(candidate.id);
    try {
      await rejectCandidate(apiBaseUrl, candidate.id, '用户在 Curator 操作台选择忽略');
      onToast?.(`已忽略「${candidate.title}」；记录和来源仍保留。`);
    } catch (cause) { onToast?.(errorText(cause, '忽略候选没有成功。')); }
    finally { setCandidateBusyId(''); await Promise.all([loadCandidates(), loadCuratorStatus()]); }
  };

  const rollbackCandidateSkill = async (candidate: SkillCandidate) => {
    setCandidateBusyId(candidate.id);
    try {
      await rollbackCandidate(apiBaseUrl, candidate.id);
      await useAtlasStore.getState().refreshSkills();
      onToast?.(`已回滚「${candidate.title}」；来源运行 ${candidate.source_runs.join('、') || '未知'}`);
    } catch (cause) {
      onToast?.(errorText(cause, '回滚没有成功，请稍后再试。'));
    } finally {
      setCandidateBusyId('');
      await loadCandidates();
    }
  };

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div>
        <h1>自动追新</h1>
        <p>把 Atlas 里所有别人的东西（内核、记忆、依赖、MCP、借鉴代码）追到最新；同时盯着上游仓库的新能力，给出保持 / 升级 / 替换建议。</p>
      </div>
      <div className="btns">
        <button className="btn ghost" onClick={() => void refreshAll()}
          disabled={checkBusy || Object.values(loading).some(Boolean)}>
          {Object.values(loading).some(Boolean) ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}刷新
        </button>
        <button className="btn primary" onClick={() => void checkNow()} disabled={checkBusy}>
          {checkBusy ? <LoaderCircle size={15} className="spin" /> : <Sparkles size={15} />}
          {checkBusy ? '正在检查上游…' : '检查上游动态'}
        </button>
      </div>
    </header>

    {checkSummary && checkSummary.errors.length > 0 && <div role="alert" className="error-note">
      <span className="min-w-0 flex-1">有 {checkSummary.errors.length} 个来源这次没读成功：{checkSummary.errors.join('；')}</span>
      <button className="iconbtn" aria-label="关闭检查提示" onClick={() => setCheckSummary(null)}><X size={15} /></button>
    </div>}

    <div className="grid gap-3">
      <UpstreamPanel apiBaseUrl={apiBaseUrl} onToast={onToast} />

      <Section icon={RadioTower} title="上游来源" count={sources.length} open={open.sources}
        hint="监视哪些仓库" onToggle={() => setOpen((value) => ({ ...value, sources: !value.sources }))}
        loading={loading.sources} error={errors.sources}
        onRetry={() => void loadSources()} onDismissError={() => setSection('sources', { error: '' })}>
        <SourceList sources={sources} busy={sourceBusy} onAdd={(source) => void addSource(source)}
          onRemove={(id) => void removeSource(id)} />
      </Section>

      <Section icon={ListChecks} title="上游能力差异" count={diffs.length} open={open.diffs}
        hint="新能力 / 上游更强 / 已具备 / 上游移除" onToggle={() => setOpen((value) => ({ ...value, diffs: !value.diffs }))}
        loading={loading.diffs} error={errors.diffs}
        onRetry={() => void loadDiffs()} onDismissError={() => setSection('diffs', { error: '' })}>
        <DiffList diffs={diffs} counts={counts} />
      </Section>

      <Section icon={Scale} title="对标建议（KEEP / UPGRADE / REPLACE）" count={parityRows.length} open={open.parity}
        hint="和 Atlas 现状逐项对比" onToggle={() => setOpen((value) => ({ ...value, parity: !value.parity }))}
        loading={loading.parity} error={errors.parity}
        onRetry={() => void loadParity()} onDismissError={() => setSection('parity', { error: '' })}>
        <ParitySuggestions rows={parityRows} patchProposal={patchProposal} />
      </Section>

      <Section icon={ScrollText} title="任务书草稿" count={drafts.length} open={open.drafts}
        hint="批准后隔离施工" onToggle={() => setOpen((value) => ({ ...value, drafts: !value.drafts }))}
        loading={loading.drafts} error={errors.drafts}
        onRetry={() => void loadDrafts()} onDismissError={() => setSection('drafts', { error: '' })}>
        <DraftList drafts={drafts} busyId={draftBusyId} generating={generating}
          onApprove={(draft) => void approve(draft)} onGenerate={() => void generate()} />
      </Section>

      <Section icon={GitBranch} title="隔离分支" count={branches.length} open={open.branches}
        hint="合并需要人工执行" onToggle={() => setOpen((value) => ({ ...value, branches: !value.branches }))}
        loading={loading.branches} error={errors.branches}
        onRetry={() => void loadBranches()} onDismissError={() => setSection('branches', { error: '' })}>
        <BranchStatus branches={branches} note={branchNote} />
      </Section>

      <Section icon={Sparkles} title="Curator 整理台" count={curatorStatus?.candidate_count ?? candidates.length}
        open={open.candidates} hint={curatorStatus?.automatic_changes ?? '候选自动整理；已安装技能只生成建议'}
        onToggle={() => setOpen((value) => ({ ...value, candidates: !value.candidates }))}
        loading={curatorLoading || loading.candidates} error={curatorError || errors.candidates}
        onRetry={() => void Promise.all([loadCuratorStatus(), loadCandidates()])}
        onDismissError={() => { setCuratorError(''); setSection('candidates', { error: '' }); }}>
        <div className="mb-3 grid gap-2 rounded-xl border border-line bg-sunken/40 p-3 text-[12px] text-fg-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="m-0">自动整理：<b>{curatorStatus?.status === 'paused' ? '已暂停' : '运行中'}</b>
              {' · '}候选 {curatorStatus?.candidate_count ?? 0}
              {curatorStatus?.last_maintenance_at ? ` · 最近整理 ${curatorStatus.last_maintenance_at}` : ' · 尚未整理'}
            </p>
            <div className="flex gap-2">
              <button type="button" className="btn ghost h-8 px-2 text-[12px]" disabled={curatorBusy || curatorLoading}
                onClick={() => void toggleCuratorPause()}>
                {curatorStatus?.auto_maintenance_paused ? <Play size={14} /> : <Pause size={14} />}
                {curatorStatus?.auto_maintenance_paused ? '恢复自动整理' : '暂停自动整理'}
              </button>
              <button type="button" className="btn ghost h-8 px-2 text-[12px]" disabled={curatorBusy || curatorLoading}
                onClick={() => void maintainSkillCandidates()}>
                {curatorBusy ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}
                手动整理
              </button>
            </div>
          </div>
          {curatorStatus && <p className="m-0">状态计数：{Object.entries(curatorStatus.counts).map(([status, count]) => `${status} ${count}`).join(' · ') || '暂无候选'}。置顶候选会跳过自动整理。</p>}
          {curatorStatus?.installed_audit_error && <p role="status" className="m-0 text-fg-3">{curatorStatus.installed_audit_error}</p>}
          {curatorStatus?.installed_suggestions.length ? <div className="grid gap-1">
            <b>已安装技能审阅建议（不会自动修改）：</b>
            {curatorStatus.installed_suggestions.map((suggestion, index) => <p key={`${suggestion.name}:${suggestion.kind}:${suggestion.version ?? index}`} className="m-0">
              {suggestion.name}{suggestion.version ? ` ${suggestion.version}` : suggestion.versions ? ` (${suggestion.versions.join(', ')})` : ''}：{suggestion.reason} {suggestion.action}
            </p>)}
          </div> : <p className="m-0">已安装技能没有重复或过期建议；审计只提示，不会自动卸载、归档或改写。</p>}
        </div>
        <SkillCandidates candidates={candidates} busyId={candidateBusyId}
          onApprove={(candidate) => void approveCandidateSkill(candidate)}
          onRollback={(candidate) => void rollbackCandidateSkill(candidate)}
          onPin={(candidate) => void pinSkillCandidate(candidate)}
          onIgnore={(candidate) => void ignoreSkillCandidate(candidate)} />
      </Section>
    </div>
  </div></div>;
}
