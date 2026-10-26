import { describe, expect, it } from 'vitest';
import { shouldSuggestSkillExtraction } from './skillExtraction';

describe('shouldSuggestSkillExtraction', () => {
  it('keeps greetings and simple question-and-answer turns quiet', () => {
    expect(shouldSuggestSkillExtraction([], ['你好'])).toBe(false);
    expect(shouldSuggestSkillExtraction([], ['只回复两个字：在呢'])).toBe(false);
  });

  it('does not suggest a skill after one tool step', () => {
    expect(shouldSuggestSkillExtraction([{ type: 'tool.started', id: 'read-1' }], ['看这个文件'])).toBe(false);
  });

  it('suggests after multi-step tool work, repeated corrections, or explicit praise', () => {
    expect(shouldSuggestSkillExtraction([
      { type: 'tool.started', id: 'read-1' }, { type: 'tool.started', id: 'edit-1' },
    ], ['修下这个问题'])).toBe(true);
    expect(shouldSuggestSkillExtraction([], ['不对，接口还没对', '再改一下'])).toBe(true);
    expect(shouldSuggestSkillExtraction([], ['谢谢，正是我想要的'])).toBe(true);
  });
});
