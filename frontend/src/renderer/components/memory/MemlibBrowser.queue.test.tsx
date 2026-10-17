import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../services/api';
import { FailedQueuePanel, fetchFailedQueue, retryFailedQueue, type FailedQueueItem } from './MemlibBrowser';

vi.mock('../../services/api', () => ({ api: vi.fn() }));

const items: FailedQueueItem[] = [{
  id: 42,
  created: '2026-10-17T09:30:00+08:00',
  session: 'session-abc',
  stage: 'extract',
  attempts: 3,
  last_error: '模型暂时不可用',
}];

describe('MemlibBrowser failed queue', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows failed items and both individual and bulk retry actions', () => {
    const html = renderToStaticMarkup(<FailedQueuePanel items={items} busyId={null} error="" onRetry={() => undefined} onRefresh={() => undefined} />);
    expect(html).toContain('失败队列');
    expect(html).toContain('session-abc');
    expect(html).toContain('模型暂时不可用');
    expect(html).toContain('重试此项');
    expect(html).toContain('全部重试');
  });

  it('shows queue request errors in the visible failure area', () => {
    const html = renderToStaticMarkup(<FailedQueuePanel items={[]} busyId={null} error="HTTP 503：队列不可用" onRetry={() => undefined} onRefresh={() => undefined} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain('HTTP 503：队列不可用');
  });

  it('loads failed queue rows through the shared API client', async () => {
    vi.mocked(api).mockResolvedValue({ items });
    await expect(fetchFailedQueue('http://atlas')).resolves.toEqual(items);
    expect(api).toHaveBeenCalledWith('http://atlas', '/api/memlib/queue/failed?limit=100');
  });

  it('posts a specific failed id and returns the retried count', async () => {
    vi.mocked(api).mockResolvedValue({ retried: 1 });
    await expect(retryFailedQueue('http://atlas', 42)).resolves.toEqual({ retried: 1 });
    expect(api).toHaveBeenCalledWith('http://atlas', '/api/memlib/queue/retry', { method: 'POST', json: { id: 42 } });
  });

  it('posts null to retry all failed items', async () => {
    vi.mocked(api).mockResolvedValue({ retried: 4 });
    await expect(retryFailedQueue('http://atlas', null)).resolves.toEqual({ retried: 4 });
    expect(api).toHaveBeenCalledWith('http://atlas', '/api/memlib/queue/retry', { method: 'POST', json: { id: null } });
  });
});
