/**
 * App-wide keyboard shortcuts. Defaults live here; the user's rebinds are stored per machine
 * and override them. A combo is written like "Ctrl+Shift+K" (Ctrl also matches Cmd on macOS).
 */
export type ShortcutAction =
  | 'palette' | 'newTask' | 'settings' | 'nextTab' | 'prevTab' | 'closeTab'
  | 'toggleSidebar' | 'toggleInspector' | 'focusComposer' | 'stopRun';

export const SHORTCUTS: Array<{ action: ShortcutAction; label: string; hint?: string; combo: string }> = [
  { action: 'palette', label: '搜索与命令', combo: 'Ctrl+K' },
  { action: 'newTask', label: '新任务', combo: 'Ctrl+N' },
  { action: 'settings', label: '打开设置', combo: 'Ctrl+,' },
  { action: 'nextTab', label: '下一个标签页', combo: 'Ctrl+Tab' },
  { action: 'prevTab', label: '上一个标签页', combo: 'Ctrl+Shift+Tab' },
  { action: 'closeTab', label: '关闭当前标签页', combo: 'Ctrl+W' },
  { action: 'toggleSidebar', label: '收起/展开侧边栏', combo: 'Ctrl+B' },
  { action: 'toggleInspector', label: '打开/关闭任务面板', combo: 'Ctrl+.' },
  { action: 'focusComposer', label: '跳到输入框', combo: 'Ctrl+L' },
  { action: 'stopRun', label: '停止当前任务', hint: '只在任务运行时有效', combo: 'Ctrl+Shift+Backspace' },
];

const KEY = 'atlas.shortcuts';

export function loadBindings(): Record<ShortcutAction, string> {
  const defaults = Object.fromEntries(SHORTCUTS.map((item) => [item.action, item.combo])) as Record<ShortcutAction, string>;
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<Record<ShortcutAction, string>>;
    for (const item of SHORTCUTS) if (typeof saved[item.action] === 'string') defaults[item.action] = saved[item.action]!;
  } catch { /* storage unavailable or corrupt: defaults */ }
  return defaults;
}

export function saveBindings(bindings: Record<ShortcutAction, string>) {
  const defaults = Object.fromEntries(SHORTCUTS.map((item) => [item.action, item.combo]));
  const changed = Object.fromEntries(Object.entries(bindings).filter(([action, combo]) => defaults[action] !== combo));
  try { localStorage.setItem(KEY, JSON.stringify(changed)); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event('atlas:shortcuts'));
}

const KEY_NAMES: Record<string, string> = { ' ': 'Space', ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Escape: 'Esc' };

/** "Ctrl+Shift+K" for a keydown, or '' while only modifiers are held. */
export function comboFromEvent(event: KeyboardEvent): string {
  if (['Control', 'Shift', 'Alt', 'Meta'].includes(event.key)) return '';
  const parts: string[] = [];
  if (event.ctrlKey || event.metaKey) parts.push('Ctrl');
  if (event.altKey) parts.push('Alt');
  if (event.shiftKey) parts.push('Shift');
  const key = KEY_NAMES[event.key] ?? (event.key.length === 1 ? event.key.toUpperCase() : event.key);
  return [...parts, key].join('+');
}

export function matchShortcut(event: KeyboardEvent, bindings: Record<ShortcutAction, string>): ShortcutAction | null {
  const combo = comboFromEvent(event);
  if (!combo) return null;
  const found = (Object.entries(bindings) as Array<[ShortcutAction, string]>).find(([, value]) => value.toUpperCase() === combo.toUpperCase());
  return found?.[0] ?? null;
}
