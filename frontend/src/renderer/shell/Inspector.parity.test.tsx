import type { ComponentProps } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Inspector from './Inspector';
import { registerInspectorTab } from './inspectorTabs';

describe('inspector extension rendering', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('renders a contributed tab with conversation context and exposes dock controls', () => {
    vi.stubGlobal('window', { innerWidth: 1200 });
    vi.stubGlobal('localStorage', { getItem: () => null });
    const dispose = registerInspectorTab({ id: 'parity:metrics', label: 'Metrics', render: ({ conversationId }) => <section>Metrics for {conversationId}</section> });
    const noop = vi.fn();
    const props: ComponentProps<typeof Inspector> = {
      tab: 'parity:metrics', onTab: noop, onClose: noop, canvasEvents: [], artifacts: [], modelName: 'test',
      tools: [], skills: [], activeSkills: [], capabilities: [], apiBaseUrl: 'http://127.0.0.1:8876', connected: false,
      onToast: noop, workspace: null, onChooseWorkspace: noop, browserUrl: '', onBrowserUrl: noop,
      browserSuggestions: [], onPick: noop, terminalCommand: null, onSendToAtlas: noop, onPreview: noop,
      conversationId: 'session-a', worktree: null, onWorktreeChanged: noop, onAsk: noop,
    };
    try {
      const html = renderToStaticMarkup(<Inspector {...props} />);
      expect(html).toContain('Metrics for session-a');
      expect(html).toContain('拆分任务面板');
      expect(html).toContain('浮动任务面板');
      expect(html).toContain('role="separator"');
    } finally { dispose(); }
  });
});
