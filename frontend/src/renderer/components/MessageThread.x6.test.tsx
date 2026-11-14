import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentEvent, AgentRun } from '../../types/runtime';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import MessageThread from './MessageThread';

vi.mock('react-virtuoso', async () => {
  const { forwardRef } = await import('react');
  return { Virtuoso: forwardRef(({ data, itemContent }: { data: unknown[]; itemContent: (index: number, row: unknown) => unknown }, _ref) => <div>{data.map((row, index) => <section key={index}>{itemContent(index, row) as never}</section>)}</div>) };
});
vi.mock('./ConversationActivity', () => ({ TimelineRow: () => null }));
vi.mock('./ConversationMessage', () => ({ default: ({ content }: { content: string }) => <p>{content}</p> }));
vi.mock('./ComputerUseTrail', () => ({ default: () => null }));
vi.mock('./conversation-search/ConversationSearch', () => ({
  ConversationSearch: () => null, clearConversationHighlights: vi.fn(), findConversationMatches: () => [], highlightConversationRow: vi.fn(),
}));

const first = { id: 'm-100', conversation_id: 'session-1', role: 'user', content: 'Latest question', created_at: '' };
let view: ReactTestRenderer | undefined;
const mount = async () => {
  const node = Object.assign(new EventTarget(), { clientHeight: 600, scrollBy: vi.fn(), querySelectorAll: () => [] });
  await act(async () => { view = create(<MessageThread history={[first]} username="User" historyActions={() => null}
    emptyState={null} footerNote={null} threadRef={{ current: null }} setTab={vi.fn()} />, {
    createNodeMock: (element) => element.props['aria-label'] === '任务活动' ? node : null,
  }); });
  return view!;
};

beforeEach(() => {
  vi.stubGlobal('window', new EventTarget());
  vi.stubGlobal('document', new EventTarget());
  useAtlasStore.setState({ activeConversationId: 'session-1', activeRunId: null, runs: [], busy: false, paused: false,
    conversationMessages: { 'session-1': [first] }, messagesHasEarlier: { 'session-1': true }, loadingEarlierConversationId: null,
    loadingMessagesConversationId: null, answers: {}, profiles: [] });
});
afterEach(() => { if (view) act(() => view!.unmount()); view = undefined; vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('MessageThread history and alternate view', () => {
  it('loads history through the visible control and removes it when the lookahead proves there is no older page', async () => {
    const getMessages = vi.spyOn(backend, 'getMessages').mockResolvedValue([{ id: 'm-0', conversation_id: 'session-1', role: 'user', content: 'First question' }]);
    const thread = await mount();
    const earlier = thread.root.findAllByType('button').find((button) => button.children.includes('载入更早的消息'))!;
    expect(earlier).toBeTruthy();
    await act(async () => { earlier.props.onClick(); });
    expect(getMessages).toHaveBeenCalledWith('session-1', { limit: 101, beforeId: 'm-100' });
    expect(thread.root.findAllByType('button').filter((button) => button.children.includes('载入更早的消息'))).toHaveLength(0);
  });

  it('switches between chat and the readable trajectory for real renderer events', async () => {
    const event = { id: 'tool-1', runId: 'run-1', sequence: 1, timestamp: '', type: 'tool.started', data: { tool_name: 'read_file', arguments: 'src/main.ts' } } as AgentEvent;
    useAtlasStore.setState({ activeRunId: 'run-1', runs: [{ id: 'run-1', conversationId: 'session-1', status: 'completed', events: [event] } as AgentRun] });
    const thread = await mount();
    const button = (label: string) => thread.root.findAllByType('button').find((item) => item.children.includes(label))!;
    expect(button('对话').props['aria-pressed']).toBe(true);
    act(() => button('轨迹').props.onClick());
    expect(button('轨迹').props['aria-pressed']).toBe(true);
    expect(thread.root.findByProps({ 'aria-label': '会话轨迹' }).findAllByType('b')[0].children.join('')).toBe('开始工具 · read_file');
    act(() => button('对话').props.onClick());
    expect(thread.root.findAllByProps({ 'aria-label': '会话轨迹' })).toHaveLength(0);
  });
});
