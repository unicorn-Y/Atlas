import { cn } from '../../ui/cn';

export interface DiffCell { number: number; text: string; changed: boolean }
export interface DiffPair { before?: DiffCell; after?: DiffCell; header?: string }

export const isBinaryDiff = (diff: string) => /^(?:Binary files .* differ|GIT binary patch)/m.test(diff);

/** Align each contiguous delete/add block, keeping context and hunk line numbers intact. */
export function pairDiffLines(diff: string): DiffPair[] {
  const rows: DiffPair[] = [];
  let oldNumber = 0;
  let newNumber = 0;
  let before: DiffCell[] = [];
  let after: DiffCell[] = [];
  let inHunk = false;
  const flush = () => {
    for (let index = 0; index < Math.max(before.length, after.length); index += 1) {
      rows.push({ before: before[index], after: after[index] });
    }
    before = []; after = [];
  };
  for (const line of diff.replace(/\n$/, '').split('\n')) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (hunk) {
      inHunk = true;
      flush(); oldNumber = Number(hunk[1]); newNumber = Number(hunk[2]);
      rows.push({ header: line });
    } else if (!inHunk && (line.startsWith('--- ') || line.startsWith('+++ ') || line.startsWith('diff --git ') || line.startsWith('index '))) {
      continue;
    } else if (line.startsWith('-')) before.push({ number: oldNumber++, text: line.slice(1), changed: true });
    else if (line.startsWith('+')) after.push({ number: newNumber++, text: line.slice(1), changed: true });
    else {
      flush();
      if (line.startsWith(' ')) rows.push({ before: { number: oldNumber++, text: line.slice(1), changed: false }, after: { number: newNumber++, text: line.slice(1), changed: false } });
      else if (line) rows.push({ header: line });
    }
  }
  flush();
  return rows;
}

export function DiffFilePreview({ path, diff }: { path: string; diff: string }) {
  const lines = diff.split('\n');
  return <div aria-label={`${path} 改动预览`} data-no-i18n className="max-w-[min(36rem,75vw)] py-1">
    <p className="m-0 mb-1 break-all font-medium">{path}</p>
    {isBinaryDiff(diff) ? <p role="status" className="m-0 text-fg-3">二进制文件 · 无文本差异预览</p>
      : <pre className="m-0 max-h-64 overflow-hidden whitespace-pre-wrap break-all font-mono text-[11px] text-fg-2">{lines.slice(0, 20).join('\n') || '没有文本改动'}</pre>}
    {!isBinaryDiff(diff) && lines.length > 20 && <p className="m-0 mt-1 text-fg-3">预览前 20 行，打开文件查看完整差异。</p>}
  </div>;
}

export function SideBySideDiff({ diff, path, wrap = false }: { diff: string; path: string; wrap?: boolean }) {
  if (isBinaryDiff(diff)) return <p role="status" className="m-0 px-3 py-2 font-sans text-fg-3">二进制文件 · {path} · 无文本差异预览</p>;
  return <div role="table" aria-label={`${path} 并排差异`} className="min-w-0">
    <div role="row" className="grid grid-cols-2 border-y border-line bg-sunken font-sans text-fg-3">
      <div role="columnheader" className="px-3 py-1">修改前</div><div role="columnheader" className="border-l border-line px-3 py-1">修改后</div>
    </div>
    {pairDiffLines(diff).map((row, index) => row.header !== undefined
      ? <div role="row" key={index} className="px-3 py-1 text-fg-3"><div role="cell">{row.header}</div></div>
      : <div role="row" key={index} className="grid grid-cols-2">
        {(['before', 'after'] as const).map((side) => {
          const cell = row[side];
          return <div role="cell" key={side} className={cn('flex min-w-0 overflow-auto', side === 'after' && 'border-l border-line', cell?.changed && (side === 'before' ? 'bg-danger-soft' : 'bg-ok-soft'))}>
            <span className="w-9 shrink-0 pr-2 text-right tabular-nums text-fg-3 select-none">{cell?.number ?? ''}</span>
            <code title={cell?.text} className={cn('min-w-0 flex-1 pr-3 text-fg-2', wrap ? 'whitespace-pre-wrap break-all' : 'whitespace-pre')}>{cell?.text || ' '}</code>
          </div>;
        })}
      </div>)}
  </div>;
}
