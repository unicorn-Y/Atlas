import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { getComputerStatus } from '../../services/x2Api';
import { ComputerDriverLabel } from './ComputerStatusSection';

afterEach(() => vi.unstubAllGlobals());

describe('computer status driver payload', () => {
  it('renders the driver object returned by the desktop backend as readable text', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      ready: true,
      driver: { version: '0.28.2', platform: 'win32' },
    }), { status: 200 })));

    const status = await getComputerStatus('http://atlas.test');
    const html = renderToStaticMarkup(<ComputerDriverLabel driver={status.driver} />);

    expect(html).toContain('驱动：0.28.2 (win32)');
  });

  it('continues to render historical string driver values', () => {
    expect(renderToStaticMarkup(<ComputerDriverLabel driver="cua" />)).toContain('驱动：cua');
  });

  it('uses a readable fallback when the backend has no detected driver version', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      ready: true,
      driver: { version: null, platform: 'win32' },
    }), { status: 200 })));

    const status = await getComputerStatus('http://atlas.test');
    const html = renderToStaticMarkup(<ComputerDriverLabel driver={status.driver} />);

    expect(html).toContain('驱动：未知版本 (win32)');
    expect(html).not.toContain('null');
  });
});
