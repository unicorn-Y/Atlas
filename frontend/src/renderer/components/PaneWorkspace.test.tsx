import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ConversationSummary } from '@atlas/backend-adapter';

vi.mock('./SidePane', () => ({ default: () => 'side pane content' }));
const { default: PaneWorkspace } = await import('./PaneWorkspace');

describe('PaneWorkspace', () => {
  afterEach(() => { Reflect.deleteProperty(globalThis, 'localStorage'); });

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
});
