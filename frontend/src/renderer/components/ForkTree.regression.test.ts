import { describe, expect, it, vi } from 'vitest';
import { loadConversationBranches } from './ForkTree';

describe('ForkTree branch loading', () => {
  it('does not request branches while there is no active conversation id', async () => {
    const load = vi.fn(async (_id: string) => []);

    await expect(loadConversationBranches('', load)).resolves.toEqual([]);
    expect(load).not.toHaveBeenCalled();
  });
});
