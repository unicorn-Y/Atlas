import { describe, expect, it, vi } from 'vitest';
import { applyRewrittenDraft, matchCommands, matchSkillSuggestions, mentionAt, selectedSkillCalls, type SlashCommand } from './Composer';

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

describe('mentionAt', () => {
  it('finds the @file or #conversation being typed at the end', () => {
    expect(mentionAt('look at @src/ap')).toEqual({ trigger: '@', query: 'src/ap', start: 8 });
    expect(mentionAt('#')).toEqual({ trigger: '#', query: '', start: 0 });
    expect(mentionAt('compare with #design')).toMatchObject({ trigger: '#', query: 'design' });
  });

  it('ignores emails, finished words and mid-word symbols', () => {
    expect(mentionAt('mail me@example.com')).toBeNull();
    expect(mentionAt('@file done ')).toBeNull();
    expect(mentionAt('issue#12')).toBeNull();
  });
});

describe('skill mention picker', () => {
  const skillCommands: SlashCommand[] = [
    { id: 'skill-review', label: '/review', hint: 'Review a pull request', source: 'Workspace skill', run: vi.fn() },
    { id: 'skill-plan', label: '/plan', hint: 'Create an implementation plan', source: 'Built-in', run: vi.fn() },
  ];

  it('filters skills by the typed query and preserves description/source for the picker', () => {
    expect(matchSkillSuggestions('rev', skillCommands)).toEqual([expect.objectContaining({
      id: 'skill-review', label: '$review', hint: 'Review a pull request', source: 'Workspace skill',
    })]);
  });

  it('previews the explicit skill invocations in the current message', () => {
    expect(selectedSkillCalls('Please $review this change and $plan the follow-up', skillCommands)).toEqual([
      { name: 'review', description: 'Review a pull request', source: 'Workspace skill' },
      { name: 'plan', description: 'Create an implementation plan', source: 'Built-in' },
    ]);
    expect(selectedSkillCalls('ordinary text', skillCommands)).toEqual([]);
  });
});

describe('applyRewrittenDraft', () => {
  it('replaces the draft with an edited preview or appends it without losing the draft', () => {
    expect(applyRewrittenDraft('old draft', '  rewritten prompt  ', false)).toBe('rewritten prompt');
    expect(applyRewrittenDraft('old draft', '  refined answer  ', true)).toBe('old draft\n\nrefined answer');
    expect(applyRewrittenDraft('', ' rewritten ', true)).toBe('rewritten');
  });
});
