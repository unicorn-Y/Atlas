import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import ConversationQueuePanel from './ConversationQueuePanel';
import type { QueuedMessage } from '../store/useAtlasStore';

describe('ConversationQueuePanel', () => {
  const item = (id: string, files: QueuedMessage['files'] = []): QueuedMessage => ({ id, content: `Message ${id}`, attachments: [], files });
  const render = (items: QueuedMessage[], running = true, paused = false) => renderToStaticMarkup(<ConversationQueuePanel
    conversationId="session-1" items={items} paused={paused} running={running} onResume={vi.fn()} onEdit={vi.fn()}
    onSendNow={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onSteer={vi.fn()} />);

  it('shows ordered queue controls and reserves steering for messages the active run can accept', () => {
    const html = render([item('text'), item('file', [{ name: 'notes.txt', mime: 'text/plain', data_base64: 'bm90ZXM=' }])]);
    expect(html).toContain('data-conversation-id="session-1"');
    expect(html.indexOf('Message text')).toBeLessThan(html.indexOf('Message file'));
    expect(html.match(/aria-label="把这条插话进当前任务"/g)).toHaveLength(1);
    expect(html.match(/aria-label="立即发送这条消息"/g)).toHaveLength(2);
    expect(html.match(/aria-label="编辑这条待发消息"/g)).toHaveLength(2);
    expect(html.match(/aria-label="删除这条待发消息"/g)).toHaveLength(2);
    expect(html).toContain('1 个附件');
  });

  it('keeps a stopped queue visible with an explicit resume control', () => {
    const html = render([item('paused')], false, true);
    expect(html).toContain('任务已停止');
    expect(html).toContain('继续发送');
    expect(html).not.toContain('aria-label="把这条插话进当前任务"');
    expect(render([])).toBe('');
  });
});
