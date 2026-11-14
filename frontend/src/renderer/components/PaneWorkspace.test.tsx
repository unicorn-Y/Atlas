import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ConversationSummary } from '@atlas/backend-adapter';

vi.mock('./SidePane', () => ({ default: () => 'side pane content' }));
const { default: PaneWorkspace } = await import('./PaneWorkspace');

describe('PaneWorkspace', () => {
  afterEach(() => { Reflect.deleteProperty(globalThis, 'localStorage'); vi.unstubAllGlobals(); });

  it('renders a persisted recursive layout containing the primary and side sessions', () => {
    const tree = {
      kind: 'split', splitId: 'root', axis: 'row', ratio: 0.6,
      first: { kind: 'pane', id: 'main' },
      second: { kind: 'split', splitId: 'nested', axis: 'column', ratio: 0.4,
        first: { kind: 'pane', id: 'side-a' }, second: { kind: 'pane', id: 'side-b' } },
    };
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: () => JSON.stringify(tree), setItem: () => undefined, removeItem: () => undefined },
    });
    const conversation = (id: string, title: string) => ({ id, title }) as ConversationSummary;
    const markup = renderToStaticMarkup(createElement(PaneWorkspace, {
      besideId: '', activeId: 'main', conversations: [conversation('main', 'Main'), conversation('side-a', 'Side A'), conversation('side-b', 'Side B')],
      username: 'tester', onSwitch: () => undefined, onRemove: () => undefined,
      children: createElement('div', { id: 'main-pane-content' }, 'main conversation'),
    }));

    expect(markup).toContain('main-pane-content');
    expect(markup.match(/aria-label="调整分屏比例"/g)).toHaveLength(2);
    expect(markup).toContain('aria-orientation="vertical"');
    expect(markup).toContain('aria-orientation="horizontal"');
    expect(markup.match(/side pane content/g)).toHaveLength(2);
    expect(markup).toContain('data-pane-id="side-a"');
    expect(markup).toContain('data-pane-id="side-b"');
  });

  it('closes a side pane, persists the reduced split tree and preserves the main conversation', async () => {
    let saved = JSON.stringify({ kind: 'split', splitId: 'root', axis: 'row', ratio: 0.6,
      first: { kind: 'pane', id: 'main' }, second: { kind: 'pane', id: 'side' } });
    vi.stubGlobal('window', new EventTarget());
    vi.stubGlobal('localStorage', { getItem: () => saved, setItem: (_key: string, value: string) => { saved = value; }, removeItem: () => undefined });
    const onRemove = vi.fn();
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PaneWorkspace besideId="" activeId="main" conversations={[{ id: 'main', title: 'Main' }, { id: 'side', title: 'Side' }]}
      username="User" onSwitch={vi.fn()} onRemove={onRemove}><div id="main-content">main conversation</div></PaneWorkspace>); });
    act(() => { view.root.findByProps({ 'aria-label': '关闭分屏' }).props.onClick(); });
    expect(onRemove).toHaveBeenCalledWith('side');
    expect(JSON.parse(saved)).toEqual({ kind: 'pane', id: 'main' });
    expect(view.root.findByProps({ id: 'main-content' }).children).toEqual(['main conversation']);
    expect(view.root.findAllByProps({ role: 'separator' })).toHaveLength(0);
    act(() => view.unmount());
  });
});
