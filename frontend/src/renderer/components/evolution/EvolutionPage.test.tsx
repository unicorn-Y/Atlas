import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import EvolutionPage from '../../pages/EvolutionPage';
import DiffList from './DiffList';
import ParitySuggestions from './ParitySuggestions';
import DraftList from './DraftList';
import BranchStatus from './BranchStatus';
import SkillCandidates from './SkillCandidates';
import {
  approveDraft, DIFF_CLASS_LABEL, listCandidates, listEvolutionDiffs, listEvolutionSources,
  runEvolutionCheck, SUGGESTION_LABEL, type DiffClass, type EvolutionDraft, type ParityRow,
  type SkillCandidate,
} from '../../services/evolutionApi';

/** 一次性应答的 fetch 桩：按顺序返回响应，并记录每次请求（与技能页测试同一套路）。 */
function fetchStub(responses: Array<{ status: number; body?: unknown }>, requests: Array<{ url: string; init?: RequestInit }> = []): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error('测试桩没有更多应答');
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), { status: next.status });
  }) as typeof fetch;
}

const diffs = (['NEW', 'BETTER_THAN_ATLAS', 'ALREADY_HAVE', 'REGRESSION_REMOVED', 'IRRELEVANT'] as DiffClass[])
  .map((cls, index) => ({
    source: 'anthropics/claude-code', repo: 'anthropics/claude-code', entry_id: `sha-${index}`,
    kind: 'commit', title: `上游更新 ${index}`, published_at: null,
    capabilities: ['verification'], cls, evidence: DIFF_CLASS_LABEL[cls], advisory: cls !== 'IRRELEVANT',
    matched_files: index === 0 ? ['src/verify.ts'] : [],
  }));

const parityRows: ParityRow[] = [
  { capability: '停止门验证', capability_id: 'verification', source: 'anthropics/claude-code', repo: 'anthropics/claude-code',
    repo_file: 'src/verify.ts', why_stronger: '上游有强制证据门', atlas_impl: '', suggestion: 'UPGRADE', advisory: true },
  { capability: '会话压缩', capability_id: 'compact', source: 'openai/codex', repo: 'openai/codex',
    repo_file: '', why_stronger: 'Atlas 已实现', atlas_impl: 'core/atlas/session.py', suggestion: 'KEEP', advisory: true },
  { capability: '录制回放', capability_id: 'replay', source: 'browser-use/browser-use', repo: 'browser-use/browser-use',
    repo_file: 'src/replay.py', why_stronger: '上游更完整，可整体替换', atlas_impl: '旧版录制器', suggestion: 'REPLACE', advisory: true },
];

const draft: EvolutionDraft = {
  id: '2026-10-03-upgrade-verification', title: '升级：停止门验证', created: '2026-10-03T06:00:00+00:00',
  path: 'meta/drafts/2026-10-03-upgrade-verification.draft.md', source_repo: 'anthropics/claude-code',
  atlas_integration_point: 'core/atlas/session.py', acceptance: '补齐证据门后再合并', status: 'draft',
  suggestion: 'UPGRADE', branch: null, exists: true,
};

const candidate: SkillCandidate = {
  id: 'weekly-report', title: '周报助手', origin: 'from_runs', preview_md: '从 3 次成功运行沉淀。',
  status: 'candidate', description: '从 3 次成功运行沉淀。', references: ['core/atlas/session.py'],
};

describe('Evolution page shell', () => {
  it('renders the six sections with Chinese loading states, without touching other pages', () => {
    const html = renderToStaticMarkup(<EvolutionPage apiBaseUrl="http://localhost:8765" />);
    expect(html).toContain('自动追新');
    expect(html).toContain('检查上游动态');
    expect(html).toContain('aria-label="组件追新"');
    expect(html).toContain('aria-label="上游来源"');
    expect(html).toContain('aria-label="上游能力差异"');
    expect(html).toContain('aria-label="对标建议（KEEP / UPGRADE / REPLACE）"');
    expect(html).toContain('aria-label="任务书草稿"');
    expect(html).toContain('aria-label="隔离分支"');
    expect(html).toContain('aria-label="技能候选"');
    expect(html).toContain('正在读取…');
  });
});

describe('Diff list badges and pagination', () => {
  it('shows every classification badge in Chinese with its evidence', () => {
    const html = renderToStaticMarkup(<DiffList diffs={diffs} counts={{ NEW: 1, BETTER_THAN_ATLAS: 1, ALREADY_HAVE: 1, REGRESSION_REMOVED: 1, IRRELEVANT: 1 }} />);
    for (const label of Object.values(DIFF_CLASS_LABEL)) expect(html).toContain(label);
    expect(html).toContain('上游更新 0');
    expect(html).toContain('src/verify.ts');
    expect(html).toContain('本轮分类：');
  });

  it('collapses long lists behind a show-more button', () => {
    const many = Array.from({ length: 11 }, (_, index) => ({ ...diffs[index % diffs.length], entry_id: `sha-${index}`, title: `上游更新 ${index}` }));
    const html = renderToStaticMarkup(<DiffList diffs={many} counts={{}} />);
    expect(html).toContain('显示更多（还有 3 条）');
    expect(html).toContain('上游更新 7');
    expect(html).not.toContain('上游更新 8');
  });

  it('keeps an empty state pointing at sources and the check button', () => {
    const html = renderToStaticMarkup(<DiffList diffs={[]} counts={{}} />);
    expect(html).toContain('还没有分类结果');
  });
});

describe('Parity suggestions', () => {
  it('labels KEEP / UPGRADE / REPLACE rows with Atlas status and file hints', () => {
    const html = renderToStaticMarkup(<ParitySuggestions rows={parityRows} patchProposal="" />);
    expect(html).toContain(SUGGESTION_LABEL.KEEP);
    expect(html).toContain(SUGGESTION_LABEL.UPGRADE);
    expect(html).toContain(SUGGESTION_LABEL.REPLACE);
    expect(html).toContain('停止门验证');
    expect(html).toContain('core/atlas/session.py');
    expect(html).toContain('Atlas 尚无对应实现');
  });

  it('offers a read-only patch proposal preview', () => {
    const html = renderToStaticMarkup(<ParitySuggestions rows={[]} patchProposal='### CORE-PARITY PATCH（提案，不落盘）' />);
    expect(html).toContain('CORE-PARITY 补丁提案');
    expect(html).toContain('不会自动写入文档');
  });
});

describe('Draft list approve flow', () => {
  it('shows the approve button, integration point and generated file path', () => {
    const html = renderToStaticMarkup(<DraftList drafts={[draft]} busyId="" generating={false}
      onApprove={() => undefined} onGenerate={() => undefined} />);
    expect(html).toContain('批准施工');
    expect(html).toContain('升级：停止门验证');
    expect(html).toContain('core/atlas/session.py');
    expect(html).toContain('meta/drafts/2026-10-03-upgrade-verification.draft.md');
    expect(html).toContain('按建议生成草稿');
    expect(html).toContain('合并永远需要人工确认');
  });

  it('marks approved drafts with their branch instead of another approve button', () => {
    const html = renderToStaticMarkup(<DraftList drafts={[{ ...draft, status: 'approved', branch: 'evolution/upgrade-verification' }]}
      busyId="" generating={false} onApprove={() => undefined} onGenerate={() => undefined} />);
    expect(html).toContain('已批准');
    expect(html).toContain('evolution/upgrade-verification');
    expect(html).not.toContain('批准施工');
  });
});

describe('Branch status', () => {
  it('lists branches with a manual-merge status and the proposal path', () => {
    const html = renderToStaticMarkup(<BranchStatus branches={[{
      name: 'evolution/upgrade-verification', status: 'proposal',
      proposal_path: '.atlas/worktrees/upgrade-verification/MERGE-PROPOSAL.md',
      worktree: '.atlas/worktrees/upgrade-verification', base: 'main',
      created_at: '2026-10-03T06:10:00+00:00', draft_id: draft.id,
    }]} note="合并永远需要人工执行 MERGE-PROPOSAL.md 中的命令" />);
    expect(html).toContain('evolution/upgrade-verification');
    expect(html).toContain('待人工合并');
    expect(html).toContain('MERGE-PROPOSAL.md');
    expect(html).toContain('基线 main');
  });
});

describe('Skill candidates preview and approve', () => {
  it('shows origin, status and an approve action for pending candidates', () => {
    const html = renderToStaticMarkup(<SkillCandidates candidates={[candidate]} busyId="" onApprove={() => undefined} />);
    expect(html).toContain('周报助手');
    expect(html).toContain('运行沉淀');
    expect(html).toContain('候选');
    expect(html).toContain('aria-label="预览候选技能 周报助手"');
    expect(html).toContain('批准');
  });

  it('hides the approve action once a candidate is approved or merged', () => {
    const html = renderToStaticMarkup(<SkillCandidates candidates={[{ ...candidate, status: 'approved' }]} busyId="" onApprove={() => undefined} />);
    expect(html).toContain('已批准');
    expect(html).not.toContain('aria-label="批准候选技能 周报助手"');
  });
});

describe('Evolution API client', () => {
  it('normalizes wrapped and bare source lists tolerantly', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const wrapped = await listEvolutionSources('http://localhost:8765', fetchStub([
      { status: 200, body: { sources: [{ id: 'codex', repo: 'openai/codex', kind: 'commit', state: { last_checked_at: '2026-10-03T06:00:00+00:00' }, cached_entries: 7 }] } },
    ], requests));
    expect(requests[0].url).toBe('http://localhost:8765/api/evolution/sources');
    expect(wrapped).toEqual([expect.objectContaining({ id: 'codex', repo: 'openai/codex', kind: 'commit', last_checked: '2026-10-03T06:00:00+00:00', cached_entries: 7 })]);
    const bare = await listEvolutionSources('http://localhost:8765', fetchStub([{ status: 200, body: [{ id: 'x', repo: 'a/b' }] }]));
    expect(bare).toHaveLength(1);
    const junk = await listEvolutionSources('http://localhost:8765', fetchStub([{ status: 200, body: { nope: true } }]));
    expect(junk).toEqual([]);
  });

  it('summarizes the check result from either response shape', async () => {
    const fromResults = await runEvolutionCheck('http://localhost:8765', fetchStub([
      { status: 200, body: { checked_at: '2026-10-03T06:00:00+00:00', ok: false, checked: 2, results: [
        { id: 'a', repo: 'a/a', ok: true, new_entries: 3, total_entries: 9 },
        { id: 'b', repo: 'b/b', ok: false, error: '上游离线' },
      ], errors: ['上游离线'] } },
    ]));
    expect(fromResults).toEqual(expect.objectContaining({ checked: 2, ok: false, new_commits: 3, errors: ['上游离线'] }));
    const fromCounts = await runEvolutionCheck('http://localhost:8765', fetchStub([
      { status: 200, body: { checked: 4, new_commits: 5, new_diffs: 2 } },
    ]));
    expect(fromCounts).toEqual(expect.objectContaining({ checked: 4, new_commits: 5, new_diffs: 2, errors: [] }));
  });

  it('reads diffs plus counts and skips irrelevant unless asked', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const { diffs: list, counts } = await listEvolutionDiffs('http://localhost:8765', { includeIrrelevant: true }, fetchStub([
      { status: 200, body: { diffs: [{ source: 'a/b', title: 't', cls: 'NEW', reason: '新增', advisory: true }], counts: { NEW: 1 }, total_entries: 2 } },
    ], requests));
    expect(requests[0].url).toBe('http://localhost:8765/api/evolution/diffs?include_irrelevant=true');
    expect(list[0]).toEqual(expect.objectContaining({ source: 'a/b', cls: 'NEW', evidence: '新增', advisory: true }));
    expect(counts).toEqual({ NEW: 1 });
  });

  it('passes approve results through, including the graceful ok:false reason', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const skipped = await approveDraft('http://localhost:8765', 'draft 1', 'main', fetchStub([
      { status: 200, body: { ok: false, reason: '该草稿已批准过，请勿重复批准' } },
    ], requests));
    expect(requests[0].url).toBe('http://localhost:8765/api/evolution/drafts/draft%201/approve');
    expect(JSON.parse(String(requests[0].init?.body))).toEqual({ base: 'main' });
    expect(skipped).toEqual(expect.objectContaining({ ok: false, reason: '该草稿已批准过，请勿重复批准' }));
    const approved = await approveDraft('http://localhost:8765', 'draft-2', undefined, fetchStub([
      { status: 200, body: { ok: true, branch: 'evolution/x', worktree: '.atlas/worktrees/x', status: 'proposal' } },
    ]));
    expect(approved).toEqual(expect.objectContaining({ ok: true, branch: 'evolution/x', status: 'proposal' }));
  });

  it('builds a readable preview when the candidate payload has none', async () => {
    const list = await listCandidates('http://localhost:8765', fetchStub([
      { status: 200, body: { candidates: [{ id: 'c1', name: '周报助手', description: '汇总本周对话。', origin: 'from_runs', references: ['a.md', 'b.md'], status: 'candidate' }] } },
    ]));
    expect(list[0]).toEqual(expect.objectContaining({ id: 'c1', title: '周报助手', origin: 'from_runs' }));
    expect(list[0].preview_md).toContain('汇总本周对话。');
    expect(list[0].preview_md).toContain('参考资料：a.md、b.md');
  });

  it('turns network failures into a plain Chinese offline message', async () => {
    const failing: typeof fetch = (async () => { throw new TypeError('Failed to fetch'); }) as typeof fetch;
    await expect(listEvolutionSources('http://localhost:8765', failing)).rejects.toThrow('连接不上自动追新服务，请确认 Atlas 后端已启动后重试。');
  });
});
