import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ConnectionRecovery, recoverBackendConnection } from './ConnectionRecovery';

describe('backend recovery control', () => {
  it('renders a keyboard accessible retry action while disconnected', () => {
    const html = renderToStaticMarkup(<ConnectionRecovery onRetry={() => undefined} />);
    expect(html).toContain('role="status"');
    expect(html).toContain('type="button"');
    expect(html).toContain('重试连接');
  });

  it('retries the health connection when no desktop restart is available', async () => {
    const retry = vi.fn();
    await recoverBackendConnection({ retry, confirmRestart: () => true });
    expect(retry).toHaveBeenCalledOnce();
  });

  it('asks before restarting the desktop backend', async () => {
    const restart = vi.fn();
    const retry = vi.fn();
    await recoverBackendConnection({ retry, restart, confirmRestart: () => false });
    expect(restart).not.toHaveBeenCalled();
    expect(retry).not.toHaveBeenCalled();
  });

  it('restarts after the user confirms recovery', async () => {
    const restart = vi.fn().mockResolvedValue(undefined);
    await recoverBackendConnection({ retry: vi.fn(), restart, confirmRestart: () => true });
    expect(restart).toHaveBeenCalledOnce();
  });
});
