import React, { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RuntimeEventEnvelope } from '../services/runtimeEvents';
import { backend } from '../store/useAtlasStore';
import SideChat from './SideChat';

vi.mock('../ui/Dialog', () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => createElement('section', null, children),
}));
vi.mock('../ui/Button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    createElement('button', props, children),
}));
vi.mock('./ConversationMessage', () => ({
  default: ({ role, content }: { role: string; content: string }) =>
    createElement('span', { 'data-message-role': role }, content),
}));

afterEach(() => vi.restoreAllMocks());

describe('SideChat attempt rollback', () => {
  it('removes failed streamed text from the mounted component before rendering the successful attempt', async () => {
    let receive: ((event: RuntimeEventEnvelope) => void) | undefined;
    vi.spyOn(backend, 'startRun').mockImplementation(async (_request, onEvent) => {
      receive = onEvent;
    });

    let view!: ReactTestRenderer;
    await act(async () => {
      view = create(<SideChat
        open
        onClose={() => undefined}
        conversationId="sidechat-attempt-test"
        model="fixture-model"
        initialQuestion="summarize the failure"
      />);
      await Promise.resolve();
    });
    expect(receive).toBeTypeOf('function');
    const assistantText = () => view.root.findAllByProps({ 'data-message-role': 'assistant' })
      .map((node) => node.children.join('')).join('\n');
    const send = (event: string, sequence: number, data: Record<string, unknown>) => receive!({
      type: 'agent_event', event_id: `sidechat-${sequence}`, run_id: 'sidechat-attempt-test-run',
      sequence, timestamp: new Date(sequence).toISOString(), event, data,
    });

    await act(async () => { send('message.delta', 1, { content: 'OLD answer', attempt_id: 'old' }); });
    expect(assistantText()).toContain('OLD answer');

    await act(async () => { send('message.rollback', 2, { attempt_id: 'old', category: 'provider_error' }); });
    expect(assistantText()).not.toContain('OLD answer');

    await act(async () => { send('message.delta', 3, { content: 'NEW answer', attempt_id: 'new' }); });
    expect(assistantText()).toContain('NEW answer');
    expect(assistantText()).not.toContain('OLD answer');
    act(() => view.unmount());
  });
});
