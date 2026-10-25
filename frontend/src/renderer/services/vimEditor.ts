export type VimOperator = 'd' | 'y' | 'c';
export interface TextRange { start: number; end: number }
export interface VimEdit { range: TextRange; register: string; value: string; caret: number; enterInsert: boolean }

export function lineBounds(value: string, position: number): TextRange {
  const cursor = Math.max(0, Math.min(value.length, position));
  const start = value.lastIndexOf('\n', Math.max(0, cursor - 1)) + 1;
  const newline = value.indexOf('\n', cursor);
  return { start, end: newline < 0 ? value.length : newline };
}

export function moveVimCursor(value: string, position: number, key: string): number {
  const cursor = Math.max(0, Math.min(value.length, position));
  const line = lineBounds(value, cursor);
  if (key === 'h') return Math.max(line.start, cursor - 1);
  if (key === 'l') return Math.min(line.end > line.start ? line.end - 1 : line.end, cursor + 1);
  if (key === '0' || key === 'Home') return line.start;
  if (key === '$' || key === 'End') return line.end > line.start ? line.end - 1 : line.end;
  if (key === 'w') {
    const tail = value.slice(cursor);
    const firstSpace = tail.search(/\s/);
    if (firstSpace < 0) return value.length;
    const rest = tail.slice(firstSpace + 1);
    const nextWord = rest.search(/\S/);
    return cursor + firstSpace + 1 + (nextWord < 0 ? 0 : nextWord);
  }
  if (key === 'b') {
    const head = value.slice(0, cursor).replace(/\s+$/, '');
    const word = head.search(/\S+$/);
    return word < 0 ? 0 : word;
  }
  if (key === 'e') {
    let at = cursor;
    while (at < value.length && /\s/.test(value[at])) at++;
    while (at + 1 < value.length && !/\s/.test(value[at + 1])) at++;
    return at;
  }
  if (key === 'j' || key === 'k') {
    const targetStart = key === 'j' ? Math.min(value.length, line.end + (line.end < value.length ? 1 : 0)) : Math.max(0, line.start - 1);
    const targetLine = lineBounds(value, targetStart);
    return Math.min(targetStart + cursor - line.start, targetLine.end);
  }
  return cursor;
}

export function applyVimOperator(value: string, position: number, operator: VimOperator, motion: string): VimEdit | null {
  const line = lineBounds(value, position);
  let start: number;
  let end: number;
  if (motion === operator) {
    start = line.start;
    end = line.end < value.length ? line.end + 1 : line.end;
  } else {
    if (!['h', 'j', 'k', 'l', '0', '$', 'w', 'b', 'e', 'Home', 'End'].includes(motion)) return null;
    const target = moveVimCursor(value, position, motion);
    start = Math.min(position, target);
    end = Math.max(position, target);
    if (motion === 'e' || motion === 'l' || motion === '$' || motion === 'End') end = Math.min(value.length, end + 1);
  }
  return {
    range: { start, end },
    register: value.slice(start, end),
    value: operator === 'y' ? value : value.slice(0, start) + value.slice(end),
    caret: start,
    enterInsert: operator === 'c',
  };
}
