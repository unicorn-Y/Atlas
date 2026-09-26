import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import SkillDiscoveryPage from './SkillDiscoveryPage';
import { buildSkillDiscoveryUrl, canActivateLocalSkill } from './skillDiscoveryUrl';

describe('Skill discovery page', () => {
  it('renders task search and structured filters without affecting chat', () => {
    const html = renderToStaticMarkup(<SkillDiscoveryPage apiBaseUrl="http://localhost:8765" />);
    expect(html).toContain('aria-label="技能发现"');
    expect(html).toContain('aria-label="任务或技能搜索"');
    expect(html).toContain('能力筛选');
    expect(html).toContain('工具筛选');
    expect(html).toContain('来源筛选');
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
    expect(canActivateLocalSkill({ source: 'api', status: 'active' })).toBe(false);
    expect(canActivateLocalSkill({ source: 'local', status: 'disabled' })).toBe(false);
  });
});
