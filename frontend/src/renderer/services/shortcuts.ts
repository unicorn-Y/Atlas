/**
 * App-wide keyboard shortcuts. Defaults live here; user rebinds are stored per machine.
 * A combo is written like "Ctrl+Shift+K" (Ctrl also matches Cmd on macOS).
 *
 * Multi-binding, command/key search, and conflict-feedback behavior is informed by
 * ZCode (zai-org/ZCode, aac4755666d09fdcd70272fcf063c077a639015f; packages/ui/src/shortcuts)
 * and OpenCode (anomalyco/opencode, 7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937;
 * packages/app/src/settings/keybinds/keybinds.tsx). Atlas keeps its existing action IDs,
 * defaults, storage key, and single-action matchShortcut contract.
 */
export type ShortcutAction =
  | 'palette' | 'newTask' | 'settings' | 'nextTab' | 'prevTab' | 'closeTab'
  | 'toggleSidebar' | 'toggleInspector' | 'focusComposer' | 'stopRun'
  | 'sidebarSearch' | 'sidebarProjectPicker' | 'sidebarNextGroup' | 'sidebarPreviousGroup';

export type ShortcutBindings = Record<ShortcutAction, string[]>;
export type ShortcutBindingValue = string | readonly string[];

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
  { action: 'sidebarSearch', label: '侧栏搜索会话', combo: 'Ctrl+Shift+F' },
  { action: 'sidebarProjectPicker', label: '侧栏项目选择器', combo: 'Ctrl+Alt+P' },
  { action: 'sidebarNextGroup', label: '切换到下一个会话组', combo: 'Ctrl+Alt+J' },
  { action: 'sidebarPreviousGroup', label: '切换到上一个会话组', combo: 'Ctrl+Alt+K' },
];

const STORAGE_KEY = 'atlas.shortcuts';

export function defaultBindings(): ShortcutBindings {
  return Object.fromEntries(SHORTCUTS.map((item) => [item.action, [item.combo]])) as ShortcutBindings;
}

export function bindingsForAction(value: ShortcutBindingValue | undefined): string[] {
  if (Array.isArray(value)) return value.filter((combo): combo is string => typeof combo === 'string');
  return typeof value === 'string' && value ? [value] : [];
}

/** Reads the previous single-string format as well as the current array format. */
export function loadBindings(): ShortcutBindings {
  const defaults = defaultBindings();
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<Record<ShortcutAction, unknown>>;
    for (const item of SHORTCUTS) {
      const value = saved[item.action];
      if (typeof value === 'string') defaults[item.action] = value ? [value] : [];
      else if (Array.isArray(value) && value.every((combo) => typeof combo === 'string')) {
        defaults[item.action] = [...new Set(value as string[])];
      }
    }
  } catch { /* storage unavailable or corrupt: defaults */ }
  return defaults;
}

export function saveBindings(bindings: ShortcutBindings) {
  const defaults = defaultBindings();
  const changed: Partial<ShortcutBindings> = {};
  for (const { action } of SHORTCUTS) {
    const combos = bindingsForAction(bindings[action]);
    if (!sameBindings(combos, defaults[action])) changed[action] = combos;
  }
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(changed)); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event('atlas:shortcuts'));
}

export function sameBindings(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((combo, index) => shortcutSignature(combo) === shortcutSignature(right[index]));
}

const KEY_NAMES: Record<string, string> = {
  ' ': 'Space', ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Escape: 'Esc',
};

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

/** Canonical comparison key: Cmd/Meta aliases Ctrl and modifier ordering is ignored. */
export function shortcutSignature(combo: string): string {
  const tokens = combo.split('+').map((part) => part.trim()).filter(Boolean);
  if (!tokens.length) return '';
  const modifiers = new Set<string>();
  const keys: string[] = [];
  for (const token of tokens) {
    const lower = token.toLowerCase();
    if (['ctrl', 'control', 'cmd', 'command', 'meta', 'cmdorctrl'].includes(lower)) modifiers.add('CTRL');
    else if (['alt', 'option'].includes(lower)) modifiers.add('ALT');
    else if (lower === 'shift') modifiers.add('SHIFT');
    else keys.push(lower);
  }
  const aliases: Record<string, string> = {
    esc: 'escape', del: 'delete', space: 'space', '↑': 'arrowup', '↓': 'arrowdown', '←': 'arrowleft', '→': 'arrowright',
  };
  const key = keys.map((value) => aliases[value] ?? value).join('+');
  return [...['CTRL', 'ALT', 'SHIFT'].filter((modifier) => modifiers.has(modifier)), key].filter(Boolean).join('+');
}

/** A text search for either a command label or any displayed shortcut. */
export function matchesShortcutSearch(value: string, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase().replace(/[\s+_-]/g, '');
  if (!needle) return true;
  const normalized = value.toLocaleLowerCase().replace(/[\s+_-]/g, '');
  return normalized.includes(needle);
}

/** Keystroke search compares the recorded combo, including Ctrl/Meta physical equivalence. */
export function matchesShortcutKey(combo: string, keyFilter: string): boolean {
  return !keyFilter || shortcutSignature(combo) === shortcutSignature(keyFilter);
}

/** Returns a user-facing reason a newly captured global shortcut must be rejected. */
export function shortcutRejection(combo: string): string | null {
  const signature = shortcutSignature(combo);
  const parts = signature.split('+');
  const key = parts[parts.length - 1] ?? '';
  const modifiers = new Set(parts.slice(0, -1));
  if (!modifiers.has('CTRL') && !modifiers.has('ALT')) return '需要带 Ctrl 或 Alt，免得和打字冲突';

  const reservedKeys = new Set(['escape', 'enter', 'tab', 'space', 'backspace', 'delete', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright']);
  if (reservedKeys.has(key) || /^f(?:[1-9]|1[0-2])$/.test(key)) return '这是系统或界面保留键，不能分配给全局操作';

  const reservedCombos = new Set([
    'ctrl+a', 'ctrl+c', 'ctrl+v', 'ctrl+x', 'ctrl+z', 'ctrl+y', 'ctrl+shift+z',
    'ctrl+s', 'ctrl+p', 'ctrl+l', 'ctrl+r', 'ctrl+shift+r',
    'ctrl+shift+i', 'ctrl+shift+j', 'ctrl+shift+c',
  ]);
  if (reservedCombos.has(signature.toLowerCase())) return '这是系统或界面保留键，不能分配给全局操作';
  return null;
}

export function findShortcutConflict(
  action: ShortcutAction,
  combo: string,
  bindings: ShortcutBindings,
): ShortcutAction | null {
  const signature = shortcutSignature(combo);
  for (const item of SHORTCUTS) {
    if (item.action === action) continue;
    if (bindingsForAction(bindings[item.action]).some((candidate) => shortcutSignature(candidate) === signature)) return item.action;
  }
  return null;
}

export function findDuplicateBinding(action: ShortcutAction, combo: string, bindings: ShortcutBindings): boolean {
  const signature = shortcutSignature(combo);
  return bindingsForAction(bindings[action]).some((candidate) => shortcutSignature(candidate) === signature);
}

export function matchShortcut(event: KeyboardEvent, bindings: Record<ShortcutAction, ShortcutBindingValue>): ShortcutAction | null {
  const signature = shortcutSignature(comboFromEvent(event));
  if (!signature) return null;
  const found = SHORTCUTS.find(({ action }) => bindingsForAction(bindings[action])
    .some((value) => shortcutSignature(value) === signature));
  return found?.action ?? null;
}
