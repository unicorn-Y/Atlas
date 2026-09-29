/** The three looks Atlas ships with. The id is written to <html data-theme>. */
export type Theme = 'light' | 'aurora' | 'dark';

export const THEMES: Array<{ id: Theme; label: string; hint: string; swatch: string; windowColor: string }> = [
  { id: 'light', label: '白瓷', hint: '纯白纸面，几乎只用黑白', swatch: 'linear-gradient(135deg,#FFFFFF 50%,#EEEDE9 50%)', windowColor: '#EEEDE9' },
  { id: 'aurora', label: '晨光', hint: '柔和极光，半透明面板', swatch: 'linear-gradient(135deg,#E3DEFB,#FCE3D6 55%,#D8E8FB)', windowColor: '#F3F2FA' },
  { id: 'dark', label: '夜航', hint: '深夜底色，黄铜细线', swatch: 'linear-gradient(135deg,#1B2331,#07090D 60%,#D9AF69)', windowColor: '#07090D' },
];

export const isTheme = (value: unknown): value is Theme => value === 'light' || value === 'aurora' || value === 'dark';
export const themeInfo = (id: Theme) => THEMES.find((theme) => theme.id === id)!;
export const nextTheme = (id: Theme): Theme => THEMES[(THEMES.findIndex((theme) => theme.id === id) + 1) % THEMES.length].id;
