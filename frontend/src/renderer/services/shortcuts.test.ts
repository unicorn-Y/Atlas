import { afterEach, describe, expect, it, vi } from 'vitest';
import { defaultBindings, matchShortcut, SHORTCUTS } from './shortcuts';

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
});
