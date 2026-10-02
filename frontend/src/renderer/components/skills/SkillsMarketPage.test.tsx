import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import SkillCard from './SkillCard';
import InstallButton, { ConflictDialog } from './InstallButton';
import OriginBadge from './OriginBadge';
import InstalledSkillCard from './InstalledSkillCard';
import { UpdatesList } from './UpdatesTab';
import SkillsMarketPage from '../../pages/SkillsMarketPage';
import {
  installSkill, isMarketConflictError, MarketConflictError, normalizeInstalledSkills,
  originLabel, searchMarket, setSkillEnabled,
  type MarketSearchHit,
} from '../../services/skillsMarketApi';

const hit: MarketSearchHit = {
  source: 'skillssh', id: 'pdf-toolkit', name: 'PDF Toolkit',
  description: '批量合并、拆分和 OCR PDF 文件。', stars: 1200, downloads: null, installed: false,
};

/** 一次性应答的 fetch 桩：按顺序返回响应，并记录每次请求。 */
function fetchStub(responses: Array<{ status: number; body?: unknown }>, requests: Array<{ url: string; init?: RequestInit }> = []): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error('测试桩没有更多应答');
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), { status: next.status });
  }) as typeof fetch;
}

describe('Skills market page shell', () => {
  it('renders the three tabs, search field and empty states without touching the chat view', () => {
    const html = renderToStaticMarkup(<SkillsMarketPage apiBaseUrl="http://localhost:8765" />);
    expect(html).toContain('技能市场');
    expect(html).toContain('aria-label="技能页签"');
    expect(html).toContain('市场');
    expect(html).toContain('已安装');
    expect(html).toContain('更新');
    expect(html).toContain('aria-label="搜索市场技能"');
    expect(html).toContain('aria-label="技能来源管理"');
    expect(html).toContain('没有找到匹配的技能');
  });
});

describe('Skill market cards', () => {
  it('shows name, description, source kind, metrics and installed badge', () => {
    const html = renderToStaticMarkup(<SkillCard hit={hit} />);
    expect(html).toContain('PDF Toolkit');
    expect(html).toContain('批量合并、拆分和 OCR PDF 文件。');
    expect(html).toContain('skills.sh');
    expect(html).toContain('aria-label="skills.sh 星标"');
    expect(html).toContain('1.2k');
    expect(html).not.toContain('已安装');
  });

  it('marks hits that are already installed locally', () => {
    const html = renderToStaticMarkup(<SkillCard hit={{ ...hit, installed: true }} />);
    expect(html).toContain('已安装');
  });

  it('falls back to download counts when a source has no stars', () => {
    const html = renderToStaticMarkup(<SkillCard hit={{ ...hit, stars: null, downloads: 8500 }} />);
    expect(html).toContain('aria-label="skills.sh 下载量"');
    expect(html).toContain('8.5k');
  });

  it('renders the required origin badges', () => {
    expect(originLabel('local_recorded')).toBe('本机录制');
    expect(originLabel('local_evolved')).toBe('自学候选');
    expect(originLabel('plugin')).toBe('插件');
    expect(originLabel('project')).toBe('项目');
    expect(originLabel('user')).toBe('用户');
    expect(originLabel('marketplace')).toBe('市场');
    expect(originLabel(null)).toBe('本地');
    expect(renderToStaticMarkup(<OriginBadge originKind="local_recorded" />)).toContain('本机录制');
  });
});

describe('Market search client', () => {
  it('builds the encoded search request and parses tolerant results', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetcher = fetchStub([{ status: 200, body: { results: [hit, { name: 'Broken entry' }, 42, null] } }], requests);
    const results = await searchMarket('http://localhost:8765', { q: 'PDF 合并', source: 'skillssh' }, fetcher);
    expect(requests[0].url).toBe('http://localhost:8765/api/skills/market/search?q=PDF+%E5%90%88%E5%B9%B6&source=skillssh');
    expect(results).toHaveLength(2);
    expect(results[0]).toMatchObject({ source: 'skillssh', id: 'pdf-toolkit', name: 'PDF Toolkit', installed: false });
    expect(results[1].name).toBe('Broken entry');
  });

  it('omits empty query and source parameters', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    await searchMarket('http://localhost:8765', {}, fetchStub([{ status: 200, body: { results: [] } }], requests));
    expect(requests[0].url).toBe('http://localhost:8765/api/skills/market/search');
  });

  it('turns network failures into plain Chinese offline messages', async () => {
    const failing: typeof fetch = (async () => { throw new TypeError('Failed to fetch'); }) as typeof fetch;
    await expect(searchMarket('http://localhost:8765', { q: 'x' }, failing)).rejects.toThrow('连接不上技能市场，请检查网络或代理设置后重试。');
  });
});

describe('Install flow and 409 conflict', () => {
  it('posts scope and reports success', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetcher = fetchStub([{ status: 200, body: { status: 'installed' } }], requests);
    await expect(installSkill('http://localhost:8765', { source: 'skillssh', id: 'pdf-toolkit', scope: 'project' }, fetcher)).resolves.toEqual({ ok: true });
    expect(requests[0].url).toBe('http://localhost:8765/api/skills/market/install');
    expect(JSON.parse(String(requests[0].init?.body))).toEqual({ source: 'skillssh', id: 'pdf-toolkit', scope: 'project' });
  });

  it('raises a Chinese conflict error on 409 and retries with overwrite on request', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetcher = fetchStub([
      { status: 409, body: { error: '同名技能已存在' } },
      { status: 200, body: { status: 'installed' } },
    ], requests);
    await expect(installSkill('http://localhost:8765', { source: 'skillssh', id: 'pdf-toolkit', scope: 'user' }, fetcher))
      .rejects.toSatisfy((cause: unknown) => isMarketConflictError(cause) && cause.message.includes('同名技能已存在') && cause.skillName === 'pdf-toolkit');
    await expect(installSkill('http://localhost:8765', { source: 'skillssh', id: 'pdf-toolkit', scope: 'user', overwrite: true }, fetcher)).resolves.toEqual({ ok: true });
    expect(JSON.parse(String(requests[1].init?.body))).toMatchObject({ overwrite: true });
  });

  it('renders the Chinese overwrite confirmation dialog', () => {
    const html = renderToStaticMarkup(<ConflictDialog name="pdf-toolkit" onCancel={() => undefined} onOverwrite={() => undefined} />);
    expect(html).toContain('aria-label="同名技能冲突"');
    expect(html).toContain('已有一个同名的技能');
    expect(html).toContain('pdf-toolkit');
    expect(html).toContain('覆盖安装');
    expect(html).toContain('先不装了');
  });

  it('keeps the busy install button non-interactive markup friendly', () => {
    const html = renderToStaticMarkup(<InstallButton apiBaseUrl="http://localhost:8765" source="skillssh" id="pdf-toolkit" scope="user" />);
    expect(html).toContain('安装技能');
    expect(html).toContain('title="装到用户目录"');
  });
});

describe('Installed skills tab data', () => {
  it('normalizes array, wrapped and broken payloads', () => {
    const fromArray = normalizeInstalledSkills([{ name: 'a', origin_kind: 'local_recorded' }]);
    const fromWrapped = normalizeInstalledSkills({ skills: [{ name: 'b', enabled: false }] });
    const fromJunk = normalizeInstalledSkills({ nope: true });
    expect(fromArray).toEqual([expect.objectContaining({ name: 'a', origin_kind: 'local_recorded' })]);
    expect(fromWrapped).toEqual([expect.objectContaining({ name: 'b', enabled: false })]);
    expect(fromJunk).toEqual([]);
  });

  it('renders badges, enable switch, try-in-conversation and uninstall actions', () => {
    const html = renderToStaticMarkup(<InstalledSkillCard skill={{ name: '周报助手', origin_kind: 'local_evolved', version: '1.4.0', source: 'skillssh', enabled: true }}
      onToggle={() => undefined} onUninstall={() => undefined} onTryInConversation={() => undefined} />);
    expect(html).toContain('周报助手');
    expect(html).toContain('自学候选');
    expect(html).toContain('v1.4.0');
    expect(html).toContain('role="switch"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain('在对话里试用');
    expect(html).toContain('卸载');
  });

  it('treats a missing enabled endpoint (404) as tolerated, real failures as errors', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    expect(await setSkillEnabled('http://localhost:8765', 'a', false, fetchStub([{ status: 404, body: { detail: 'Not Found' } }], requests))).toBe(false);
    expect(requests[0].url).toBe('http://localhost:8765/api/skills/a/enabled');
    expect(JSON.parse(String(requests[0].init?.body))).toEqual({ enabled: false });
    await expect(setSkillEnabled('http://localhost:8765', 'a', true, fetchStub([{ status: 500 }]))).rejects.toThrow('HTTP 500');
    expect(await setSkillEnabled('http://localhost:8765', 'a', true, fetchStub([{ status: 200, body: { ok: true } }]))).toBe(true);
  });
});

describe('Updates list', () => {
  it('lists pending updates with version transitions and an update-all affordance', () => {
    const html = renderToStaticMarkup(<UpdatesList
      updates={[{ name: 'pdf-toolkit', source: 'skillssh', current_version: '1.2.0', latest_version: '1.3.0', changes: '支持加密 PDF。' }]}
      busyName="" updatingAll={false} onUpdate={() => undefined} onUpdateAll={() => undefined} onRefresh={() => undefined} loading={false} error="" />);
    expect(html).toContain('有 1 个技能可以更新');
    expect(html).toContain('pdf-toolkit');
    expect(html).toContain('1.2.0');
    expect(html).toContain('1.3.0');
    expect(html).toContain('支持加密 PDF。');
    expect(html).toContain('更新');
  });

  it('renders the up-to-date empty state and offline error with retry', () => {
    const empty = renderToStaticMarkup(<UpdatesList updates={[]} busyName="" updatingAll={false}
      onUpdate={() => undefined} onUpdateAll={() => undefined} onRefresh={() => undefined} loading={false} error="" />);
    expect(empty).toContain('所有技能都是最新的');
    const errored = renderToStaticMarkup(<UpdatesList updates={[]} busyName="" updatingAll={false}
      onUpdate={() => undefined} onUpdateAll={() => undefined} onRefresh={() => undefined} loading={false} error="连接不上技能市场，请检查网络或代理设置后重试。" />);
    expect(errored).toContain('重试');
  });
});

describe('conflict error type', () => {
  it('exposes the conflicting skill name and a default Chinese message', () => {
    const error = new MarketConflictError('pdf-toolkit');
    expect(error.skillName).toBe('pdf-toolkit');
    expect(error.status).toBe(409);
    expect(error.message).toContain('同名');
    expect(isMarketConflictError(error)).toBe(true);
    expect(isMarketConflictError(new Error('nope'))).toBe(false);
  });
});
