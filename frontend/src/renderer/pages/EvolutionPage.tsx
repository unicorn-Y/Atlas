import { useCallback, useEffect, useState } from 'react';
import {
  GitBranch, ListChecks, LoaderCircle, RadioTower, RefreshCw, Scale, ScrollText, Sparkles, X,
} from 'lucide-react';
import {
  approveCandidate, approveDraft, addEvolutionSource, generateDrafts, listBranches, listCandidates,
  listEvolutionDiffs, listEvolutionSources, listDrafts, listParityRows, removeEvolutionSource,
  runEvolutionCheck, type EvolutionBranch, type EvolutionCheckResult, type EvolutionDiff,
  type EvolutionDraft, type EvolutionSource, type EvolutionSourceKind, type ParityRow,
  type SkillCandidate,
} from '../services/evolutionApi';
import Section from '../components/evolution/Section';
import SourceList from '../components/evolution/SourceList';
import DiffList from '../components/evolution/DiffList';
import ParitySuggestions from '../components/evolution/ParitySuggestions';
import DraftList from '../components/evolution/DraftList';
import BranchStatus from '../components/evolution/BranchStatus';
import SkillCandidates from '../components/evolution/SkillCandidates';
import UpstreamPanel from '../components/evolution/UpstreamPanel';
import DiscoveryPanel from '../components/evolution/DiscoveryPanel';

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

  useEffect(() => {
    void loadSources(); void loadDiffs(); void loadParity();
    void loadDrafts(); void loadBranches(); void loadCandidates();
  }, [loadSources, loadDiffs, loadParity, loadDrafts, loadBranches, loadCandidates]);

  const refreshAll = async () => {
    await Promise.all([loadSources(), loadDiffs(), loadParity(), loadDrafts(), loadBranches(), loadCandidates()]);
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
      onToast?.(`已批准「${candidate.title}」，技能包会交给技能库`);
    } catch (cause) {
      onToast?.(errorText(cause, '批准没有成功，请稍后再试。'));
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
      <DiscoveryPanel apiBaseUrl={apiBaseUrl} onToast={onToast} onDraftsChanged={() => void loadDrafts()} />

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

      <Section icon={Sparkles} title="技能候选" count={candidates.length} open={open.candidates}
        hint="先预览再批准" onToggle={() => setOpen((value) => ({ ...value, candidates: !value.candidates }))}
        loading={loading.candidates} error={errors.candidates}
        onRetry={() => void loadCandidates()} onDismissError={() => setSection('candidates', { error: '' })}>
        <SkillCandidates candidates={candidates} busyId={candidateBusyId}
          onApprove={(candidate) => void approveCandidateSkill(candidate)} />
      </Section>
    </div>
  </div></div>;
}
