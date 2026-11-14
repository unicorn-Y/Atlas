import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReleaseUpdateStatus } from '../../shared/ipc';
import { checkUpdateChannel, MandatoryUpdateDialog } from './UpdateBanner';

const release: ReleaseUpdateStatus = {
  supported: true, available: true, current: '1.0.0', latest: '2.0.0',
  minimumVersion: '1.5.0', mandatory: true, assetName: 'Atlas-2.0.0-Setup.exe',
};

const render = (overrides: Partial<ReleaseUpdateStatus> = {}, busy = false, progress = 0) => renderToStaticMarkup(
  <MandatoryUpdateDialog release={{ ...release, ...overrides }} busy={busy} progress={progress} onDownload={() => undefined} />,
);

describe('mandatory release update dialog', () => {
  it('explains the supported version and offers installation without skip or dismiss actions', () => {
    const html = render();
    expect(html).toContain('<dialog');
    expect(html).toContain('aria-label="必须更新 Atlas"');
    expect(html).toContain('最低支持版本为 1.5.0');
    expect(html).toContain('下载并安装受支持版本');
    expect(html).not.toContain('跳过这个版本');
    expect(html).not.toContain('稍后提醒');
    expect(html).not.toContain('关闭更新提示');
  });

  it('keeps an unsupported client locked when the release has no installer', () => {
    const html = render({ assetName: undefined });
    expect(html).toContain('disabled=""');
    expect(html).toContain('应用将保持锁定');
  });

  it('shows download progress and retryable verification errors in the mandatory dialog', () => {
    expect(render({}, true, 42)).toContain('正在下载 42%');
    const html = render({ error: 'SHA256 不匹配' });
    expect(html).toContain('role="alert"');
    expect(html).toContain('SHA256 不匹配');
    expect(html).not.toContain('disabled=""');
  });

  it('rejects a release API error so the coordinator records and backs off failed checks', async () => {
    await expect(checkUpdateChannel({ checkReleaseUpdate: async () => ({
      supported: true, available: false, current: '1.0.0', error: '更新服务返回 HTTP 503',
    }) }, 'release', 'https://updates.example/release')).rejects.toThrow('更新服务返回 HTTP 503');
  });

  it('continues the source channel when its optional release check fails', async () => {
    const source = { supported: true, available: false, behind: 0, commits: [] };
    await expect(checkUpdateChannel({
      checkForUpdate: async () => source,
      checkReleaseUpdate: async () => { throw new Error('offline'); },
    }, 'source', 'https://updates.example/release')).resolves.toEqual({ source, release: null });
  });
});
