import { describe, expect, it, vi } from 'vitest';
import { matchCommands, type SlashCommand } from './Composer';

const commands: SlashCommand[] = [
  { id: 'new', label: '/new', run: vi.fn() },
  { id: 'export', label: '/export', run: vi.fn() },
  { id: 'rename', label: '/rename', takesArgument: true, run: vi.fn() },
];

describe('matchCommands', () => {
  it('lists commands while typing a slash word', () => {
    expect(matchCommands('/', commands).map((item) => item.id)).toEqual(['new', 'export', 'rename']);
    expect(matchCommands('/ex', commands).map((item) => item.id)).toEqual(['export']);
  });

  it('keeps an argument command selected after its name, and ignores ordinary text', () => {
    expect(matchCommands('/rename 新名字', commands).map((item) => item.id)).toEqual(['rename']);
    expect(matchCommands('/new something', commands)).toEqual([]);
    expect(matchCommands('please /new', commands)).toEqual([]);
    expect(matchCommands('/path/to/file 看一下', commands)).toEqual([]);
  });
});
