import { describe, expect, it } from 'vitest';
import { applyVimOperator, lineBounds, moveVimCursor } from './vimEditor';

describe('Vim message editor state operations', () => {
  it('moves by line, word and vertical position without crossing invalid bounds', () => {
    const value = 'one two\nthree';
    expect(lineBounds(value, 5)).toEqual({ start: 0, end: 7 });
    expect(moveVimCursor(value, 0, 'w')).toBe(4);
    expect(moveVimCursor(value, 5, 'b')).toBe(4);
    expect(moveVimCursor(value, 0, 'e')).toBe(2);
    expect(moveVimCursor(value, 1, 'j')).toBe(9);
    expect(moveVimCursor(value, 0, 'h')).toBe(0);
    expect(moveVimCursor(value, 6, 'l')).toBe(6);
  });

  it('applies line and motion operators, yanks without changing text and enters insert for change', () => {
    expect(applyVimOperator('one\ntwo', 1, 'd', 'd')).toMatchObject({ register: 'one\n', value: 'two', caret: 0, enterInsert: false });
    expect(applyVimOperator('one two', 0, 'd', 'w')).toMatchObject({ register: 'one ', value: 'two', caret: 0 });
    expect(applyVimOperator('one', 0, 'd', '$')).toMatchObject({ register: 'one', value: '', caret: 0 });
    expect(applyVimOperator('one two', 4, 'y', 'w')).toMatchObject({ register: 'two', value: 'one two' });
    expect(applyVimOperator('one two', 4, 'c', 'c')).toMatchObject({ register: 'one two', value: '', enterInsert: true });
    expect(applyVimOperator('one', 0, 'd', 'q')).toBeNull();
  });
});
