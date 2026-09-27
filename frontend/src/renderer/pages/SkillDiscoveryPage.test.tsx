import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import SkillDiscoveryPage from './SkillDiscoveryPage';
import { buildSkillDiscoveryUrl, canActivateLocalSkill } from './skillDiscoveryUrl';
import { approveSkillInstallation, formatCanonicalDependencies, lifecycleUpdateAction, localPackageReviewState, remoteSkillLabel, reviewGateState } from './skillAcquisitionReview';

describe('Skill discovery page', () => {
  it('renders task search and structured filters without affecting chat', () => {
    const html = renderToStaticMarkup(<SkillDiscoveryPage apiBaseUrl="http://localhost:8765" />);
    expect(html).toContain('aria-label="技能发现"');
    expect(html).toContain('aria-label="任务或技能搜索"');
    expect(html).toContain('能力筛选');
    expect(html).toContain('工具筛选');
    expect(html).toContain('来源筛选');
    expect(html).toContain('Local');
    expect(html).toContain('External Catalog');
    expect(html).toContain('All');
    expect(html).toContain('本地搜索保持离线可用');
    expect(html).toContain('aria-label="导入 Skill package"');
    expect(html).toContain('lifecycle 审批');
  });

  it('does not offer the local activation path for remote records', () => {
    expect(canActivateLocalSkill({ source: 'skills.sh', status: 'active' })).toBe(false);
    expect(canActivateLocalSkill({ source: 'github', status: 'active' })).toBe(false);
  });

  it('keeps remote candidates distinct and applies PASS WARN BLOCK review gates', () => {
    expect(remoteSkillLabel(false)).toBe('Remote / Uninstalled');
    expect(remoteSkillLabel(true)).toBe('已安装');
    expect(reviewGateState('PASS', false)).toMatchObject({ canInstall: true, requiresWarningConfirmation: false });
    expect(reviewGateState('WARN', false)).toMatchObject({ canInstall: true, requiresWarningConfirmation: true });
    expect(reviewGateState('BLOCK', false)).toMatchObject({ canInstall: false });
    expect(reviewGateState('PASS', true)).toMatchObject({ canInstall: false });
  });

  it('requires downgrade review when the incoming version is older', () => {
    expect(lifecycleUpdateAction('1.2.0', '1.3.0')).toBe('update');
    expect(lifecycleUpdateAction('1.2.0', '1.1.9')).toBe('downgrade');
    expect(lifecycleUpdateAction('1.2.0', '1.2.0')).toBe('update');
  });

  it('renders explicit local package conflict and update candidate states', () => {
    expect(localPackageReviewState('exact_version_conflict')).toMatchObject({
      message: '同名同版本已存在；不会覆盖 Registry 或文件。', canProceed: false,
    });
    expect(localPackageReviewState('update_candidate')).toMatchObject({
      message: '这是更新/降级候选，将进入现有 lifecycle 更新/降级审批。',
      action: '经现有 lifecycle 审批更新/降级', canProceed: true,
    });
    expect(localPackageReviewState('new_skill').canProceed).toBe(true);
  });

  it('formats canonical dependency records with requested constraints', () => {
    expect(formatCanonicalDependencies([
      { kind: 'python_packages', name: 'requests', requested: '>=2,<4' },
      { kind: 'commands', name: 'ffmpeg', requested: null },
    ])).toBe('python_packages:requests >=2,<4, commands:ffmpeg');
  });

  it('uses the server approval and one-time authorization contract', async () => {
    const requests: Array<{ url: string; body: Record<string, unknown> }> = [];
    const responses = [
      new Response(JSON.stringify({ install_authorization: 'server-one-time-token' }), { status: 200 }),
      new Response(JSON.stringify({ status: 'installed' }), { status: 200 }),
    ];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push({ url: String(input), body: JSON.parse(String(init?.body)) as Record<string, unknown> });
      return responses.shift()!;
    };

    const response = await approveSkillInstallation('http://localhost:8765', 'acq-1', true, fetcher);
    expect(response.status).toBe(200);
    expect(requests.map((request) => request.url)).toEqual([
      'http://localhost:8765/api/skill-catalog/approve',
      'http://localhost:8765/api/skill-catalog/install',
    ]);
    expect(requests[0].body).toEqual({ acquisition_id: 'acq-1', warnings_confirmed: true });
    expect(requests[1].body).toEqual({ acquisition_id: 'acq-1', install_authorization: 'server-one-time-token' });
    expect(requests[1].body).not.toHaveProperty('approved');
    expect(requests[1].body).not.toHaveProperty('approval_event_id');
  });

  it('builds an encoded discovery request and only offers local active activation', () => {
    const url = new URL(buildSkillDiscoveryUrl('http://localhost:8765', {
      query: 'research papers', capability: 'literature search', tool: 'arxiv', source: 'local',
    }));
    expect(url.pathname).toBe('/api/skills/discover');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: 'research papers', capability: 'literature search', tool: 'arxiv', source: 'local',
    });
    expect(canActivateLocalSkill({ source: 'local', status: 'active' })).toBe(true);
    expect(canActivateLocalSkill({ source: 'local', status: 'active' }, { trust_state: 'trusted' })).toBe(true);
    expect(canActivateLocalSkill({ source: 'local', status: 'active' }, { trust_state: 'blocked' })).toBe(false);
    expect(canActivateLocalSkill({ source: 'local', status: 'active' }, { state: 'quarantined' })).toBe(false);
    expect(canActivateLocalSkill({ source: 'api', status: 'active' })).toBe(false);
    expect(canActivateLocalSkill({ source: 'local', status: 'disabled' })).toBe(false);
  });
});
