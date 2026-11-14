import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { backend } from '../store/useAtlasStore';
import ForkTree from './ForkTree';

afterEach(() => vi.restoreAllMocks());

describe('ForkTree navigation', () => {
  it('opens the family, filters branches and navigates to the selected fork', async () => {
    const conversations = [{ id: 'source', title: 'Original' }, { id: 'fork', title: 'Alternative solution' }];
    vi.spyOn(backend, 'getConversationBranches').mockResolvedValue([
      conversations[0], { ...conversations[1], parent_session_id: 'source' },
    ]);
    const onOpen = vi.fn();
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<ForkTree conversations={conversations} activeId="source" onOpen={onOpen} />); });
    act(() => { view.root.findByProps({ title: '搜索并浏览完整分叉树' }).props.onClick(); });
    expect(view.root.findByProps({ role: 'tree' })).toBeTruthy();
    act(() => { view.root.findByProps({ 'aria-label': '搜索分支' }).props.onChange({ target: { value: 'Alternative' } }); });
    const rows = view.root.findAllByProps({ role: 'treeitem' });
    expect(rows).toHaveLength(2); // Matching branch retains its parent for context.
    act(() => { rows[1].props.onClick(); });
    expect(onOpen).toHaveBeenCalledWith(conversations[1]);
    expect(view.root.findAllByProps({ role: 'dialog' })).toHaveLength(0);
    act(() => view.unmount());
  });
});
