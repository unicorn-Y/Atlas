/** The three looks Atlas ships with. The id is written to <html data-theme>. */
export type Theme = 'light' | 'aurora' | 'dark';

export const THEMES: Array<{ id: Theme; label: string; hint: string; swatch: string; windowColor: string }> = [
  { id: 'light', label: '白瓷', hint: '白色纸面，暖灰底，几乎只用黑白', swatch: 'linear-gradient(135deg,#FFFFFF 50%,#F4F3F0 50%)', windowColor: '#F4F3F0' },
  { id: 'aurora', label: '晨光', hint: '柔和极光，半透明面板', swatch: 'linear-gradient(135deg,#E3DEFB,#FCE3D6 55%,#D8E8FB)', windowColor: '#F1F0F8' },
  { id: 'dark', label: '夜航', hint: '中性深灰，黄铜点缀', swatch: 'linear-gradient(135deg,#232322,#0D0D0C 60%,#D9AF69)', windowColor: '#0D0D0C' },
];

export const isTheme = (value: unknown): value is Theme => value === 'light' || value === 'aurora' || value === 'dark';
export const themeInfo = (id: Theme) => THEMES.find((theme) => theme.id === id)!;
export const nextTheme = (id: Theme): Theme => THEMES[(THEMES.findIndex((theme) => theme.id === id) + 1) % THEMES.length].id;

export interface CustomTheme {
  version: 1;
  name: string;
  base: Theme;
  colors: {
    background: string;
    foreground: string;
    accent: string;
    surface: string;
    codeBackground: string;
  };
}

const CUSTOM_THEME_KEY = 'atlas.preference.custom-theme';
const APPEARANCE_KEY = 'atlas.preference.appearance';
const COLOR_KEYS = ['background', 'foreground', 'accent', 'surface', 'codeBackground'] as const;
const DEFAULT_COLORS: Record<Theme, CustomTheme['colors']> = {
  light: { background: '#F4F3F0', foreground: '#1A1A19', accent: '#A8762E', surface: '#FFFFFF', codeBackground: '#F6F6F4' },
  aurora: { background: '#F1F0F8', foreground: '#1C1D30', accent: '#5B6CF0', surface: '#FBFAFE', codeBackground: '#F1F0F8' },
  dark: { background: '#0D0D0C', foreground: '#ECECEA', accent: '#D9AF69', surface: '#171716', codeBackground: '#121211' },
};

const isSafeColor = (value: unknown): value is string => typeof value === 'string' && /^#[\da-f]{6}(?:[\da-f]{2})?$/i.test(value);
const storageGet = (key: string) => { try { return localStorage.getItem(key); } catch { return null; } };
const storageSet = (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } };

/** Make a local theme draft based on one of Atlas's built-in palettes. */
export function createCustomTheme(base: Theme, name = '我的主题'): CustomTheme {
  return { version: 1, name, base, colors: { ...DEFAULT_COLORS[base] } };
}

/** Validate the import format before persisting or applying any CSS values. */
export function parseCustomTheme(value: unknown): CustomTheme {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('主题文件必须是 JSON 对象');
  const input = value as Partial<CustomTheme> & { colors?: Partial<CustomTheme['colors']> };
  if (input.version !== 1) throw new Error('不支持这个主题版本');
  if (!isTheme(input.base)) throw new Error('主题底色必须是 light、aurora 或 dark');
  const colors = input.colors;
  if (!colors || !COLOR_KEYS.every((key) => isSafeColor(colors[key]))) throw new Error('background、foreground、accent、surface 和 codeBackground 都必须是 6 位或 8 位十六进制颜色');
  const name = typeof input.name === 'string' ? input.name.trim().slice(0, 48) : '';
  return { version: 1, name: name || '导入的主题', base: input.base, colors: Object.fromEntries(COLOR_KEYS.map((key) => [key, colors[key]])) as CustomTheme['colors'] };
}

export function readCustomTheme(): CustomTheme | null {
  const saved = storageGet(CUSTOM_THEME_KEY);
  if (!saved) return null;
  try { return parseCustomTheme(JSON.parse(saved) as unknown); } catch { return null; }
}

export function saveCustomTheme(value: unknown): CustomTheme {
  const theme = parseCustomTheme(value);
  storageSet(CUSTOM_THEME_KEY, JSON.stringify(theme));
  return theme;
}

/** Return the built-in base used to initialize App before its theme effect runs. */
export function initialTheme(fallback: Theme = 'light'): Theme {
  if (storageGet('atlas.preference.theme-mode') === 'system' && typeof matchMedia !== 'undefined') {
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  const saved = storageGet(APPEARANCE_KEY);
  if (saved === 'custom') return readCustomTheme()?.base ?? fallback;
  return isTheme(saved) ? saved : fallback;
}

function contrastColor(hex: string): string {
  const value = hex.slice(1, 7);
  const parts = [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16) / 255);
  const linear = parts.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2] > 0.42 ? '#17171B' : '#FFFFFF';
}

const CUSTOM_PROPERTIES = [
  '--bg', '--desk', '--sheet-bg', '--sheet-solid', '--card-bg', '--code-bg', '--fg', '--fg-2', '--fg-3', '--heading',
  '--brand', '--brand-soft', '--primary-bg', '--on-primary', '--selected', '--hover', '--line', '--line-strong', '--avatar-bg', '--avatar-fg',
];

/** Apply only validated colors over an existing Atlas base palette. */
export function applyCustomTheme(value: unknown): Theme {
  const theme = parseCustomTheme(value);
  if (typeof document === 'undefined') return theme.base;
  const root = document.documentElement;
  root.dataset.theme = theme.base;
  const { background, foreground, accent, surface, codeBackground } = theme.colors;
  const muted = `color-mix(in srgb, ${foreground} 70%, ${background})`;
  const faint = `color-mix(in srgb, ${foreground} 48%, ${background})`;
  const softAccent = `color-mix(in srgb, ${accent} 14%, transparent)`;
  root.style.setProperty('--bg', background);
  root.style.setProperty('--desk', background);
  root.style.setProperty('--sheet-bg', surface);
  root.style.setProperty('--sheet-solid', surface);
  root.style.setProperty('--card-bg', `color-mix(in srgb, ${surface} 92%, ${background})`);
  root.style.setProperty('--code-bg', codeBackground);
  root.style.setProperty('--fg', foreground);
  root.style.setProperty('--heading', foreground);
  root.style.setProperty('--fg-2', muted);
  root.style.setProperty('--fg-3', faint);
  root.style.setProperty('--brand', accent);
  root.style.setProperty('--brand-soft', softAccent);
  root.style.setProperty('--primary-bg', accent);
  root.style.setProperty('--on-primary', contrastColor(accent));
  root.style.setProperty('--selected', softAccent);
  root.style.setProperty('--hover', `color-mix(in srgb, ${accent} 8%, transparent)`);
  root.style.setProperty('--line', `color-mix(in srgb, ${foreground} 10%, transparent)`);
  root.style.setProperty('--line-strong', `color-mix(in srgb, ${foreground} 18%, transparent)`);
  root.style.setProperty('--avatar-bg', accent);
  root.style.setProperty('--avatar-fg', contrastColor(accent));
  return theme.base;
}

export function activateCustomTheme(value: unknown): Theme {
  const theme = saveCustomTheme(value);
  storageSet(APPEARANCE_KEY, 'custom');
  return applyCustomTheme(theme);
}

export function clearCustomTheme(): void {
  if (typeof document !== 'undefined') for (const key of CUSTOM_PROPERTIES) document.documentElement.style.removeProperty(key);
  try { localStorage.removeItem(CUSTOM_THEME_KEY); } catch { /* storage unavailable */ }
}

/** Call from App's theme effect so a saved custom palette survives reloads. */
export function applyStoredTheme(fallback: Theme): Theme {
  if (storageGet(APPEARANCE_KEY) === 'custom') {
    const custom = readCustomTheme();
    if (custom) return applyCustomTheme(custom);
  }
  if (typeof document !== 'undefined') {
    for (const key of CUSTOM_PROPERTIES) document.documentElement.style.removeProperty(key);
    document.documentElement.dataset.theme = fallback;
  }
  return fallback;
}
