import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import VoiceOverlay from './VoiceOverlay';

describe('VoiceOverlay input controls', () => {
  it('exposes listening status, captions, mute, hangup and text fallback', () => {
    const html = renderToStaticMarkup(<VoiceOverlay apiBaseUrl="http://127.0.0.1:8876" onClose={vi.fn()} onSend={vi.fn()}
      runId={null} reply="" runDone modelName="DeepSeek" />);
    expect(html).toContain('在听，你可以直接说');
    for (const label of ['静音', '挂断', '显示字幕', '转成文字对话']) expect(html).toContain(`aria-label="${label}"`);
    expect(html).toContain('aria-live="polite"');
    expect(html).toMatch(/aria-label="打断 Atlas"[^>]*disabled/);
  });
});
