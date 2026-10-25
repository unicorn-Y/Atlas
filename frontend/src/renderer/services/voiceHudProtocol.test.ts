import { describe, expect, it } from 'vitest';
import { initialHudState, reduceHudMessage } from './voiceHudProtocol';

describe('voice HUD ASR protocol', () => {
  it('advances through model preparation and listening while keeping partial text transient', () => {
    const preparing = reduceHudMessage(initialHudState(), { type: 'progress', progress: 0.42 });
    expect(preparing).toMatchObject({ status: 'preparing', detail: '正在准备语音模型 42%', transcript: '' });
    const ready = reduceHudMessage(preparing, { type: 'ready' });
    expect(ready.status).toBe('listening');
    const partial = reduceHudMessage(ready, { type: 'partial', text: '你好' });
    expect(partial.transcript).toBe('你好');
    const committed = reduceHudMessage(partial, { type: 'final', text: ' 你好 Atlas ' });
    expect(committed.committedTranscript).toBe('你好 Atlas');
    expect(reduceHudMessage(committed, { type: 'partial', text: '继续' }).transcript).toBe('你好 Atlas 继续');
  });

  it('bounds committed transcript and exposes a useful error state', () => {
    const long = reduceHudMessage(initialHudState(), { type: 'final', text: 'a'.repeat(800) });
    expect(long.committedTranscript).toHaveLength(600);
    expect(reduceHudMessage(long, { type: 'error', detail: '服务未就绪' })).toMatchObject({ status: 'error', detail: '服务未就绪' });
  });
});
