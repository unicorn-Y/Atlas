import { afterEach, describe, expect, it, vi } from 'vitest';
import { comboFromEvent, defaultBindings, matchShortcut, SHORTCUTS } from './shortcuts';

describe('focus view shortcut', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('provides one configurable Ctrl/Cmd+Shift+O binding', () => {
    const binding = SHORTCUTS.find((item) => item.action === 'toggleFocus');
    expect(binding?.combo).toBe('Ctrl+Shift+O');
    const key = (parts: Partial<KeyboardEvent>) => ({ key: 'o', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...parts }) as KeyboardEvent;
    expect(matchShortcut(key({ ctrlKey: true, shiftKey: true }), defaultBindings())).toBe('toggleFocus');
    expect(matchShortcut(key({ metaKey: true, shiftKey: true }), defaultBindings())).toBe('toggleFocus');
  });

  it('keeps chat tab close and window close as distinct defaults', () => {
    expect(SHORTCUTS.find((item) => item.action === 'closeTab')?.combo).toBe('Ctrl+W');
    expect(SHORTCUTS.find((item) => item.action === 'closeWindow')?.combo).toBe('Ctrl+Shift+W');
    const key = (parts: Partial<KeyboardEvent>) => ({ key: 'w', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...parts }) as KeyboardEvent;
    expect(matchShortcut(key({ ctrlKey: true }), defaultBindings())).toBe('closeTab');
    expect(matchShortcut(key({ ctrlKey: true, shiftKey: true }), defaultBindings())).toBe('closeWindow');
  });

  it('does not capture or run shortcuts while an IME is composing', () => {
    for (const input of [{ isComposing: true }, { keyCode: 229 }]) {
      const event = { key: 'w', ctrlKey: true, metaKey: false, shiftKey: false, altKey: false, ...input } as unknown as KeyboardEvent;
      expect(comboFromEvent(event)).toBe('');
      expect(matchShortcut(event, defaultBindings())).toBeNull();
    }
  });
});
