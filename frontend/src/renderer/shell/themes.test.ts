import { describe, expect, it } from 'vitest';
import { createCustomTheme, parseCustomTheme, parseThemeDirectoryFiles } from './themes';

describe('custom theme format', () => {
  it('migrates version 1 themes with defaults for session prompts', () => {
    const old = createCustomTheme('dark');
    const { promptBackground: _background, promptForeground: _foreground, ...legacyColors } = old.colors;
    const migrated = parseCustomTheme({ version: 1, name: 'Legacy', base: 'dark', colors: legacyColors });
    expect(migrated.version).toBe(2);
    expect(migrated.colors.promptBackground).toBe('#242422');
    expect(migrated.colors.promptForeground).toBe('#ECECEA');
  });

  it('validates a directory of themes and reports invalid JSON entries', () => {
    const valid = createCustomTheme('aurora', 'Misty');
    const result = parseThemeDirectoryFiles([
      { name: 'misty.json', text: JSON.stringify(valid) },
      { name: 'broken.json', text: '{' },
      { name: 'notes.txt', text: 'ignored' },
    ]);
    expect(result.themes.map((theme) => theme.name)).toEqual(['Misty']);
    expect(result.rejected).toEqual(['broken.json']);
  });
});
