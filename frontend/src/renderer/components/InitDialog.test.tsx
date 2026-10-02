import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { InitDialogBody } from './InitDialog';
import type { InitProposal } from '@atlas/backend-adapter';

const proposal: InitProposal = {
  path: 'C:/ws/AGENTS.md',
  exists: false,
  existing_content: '',
  proposed_content: '# Atlas\n\n- 用 pnpm 跑测试\n',
  scan: {
    languages: [{ name: 'Python', count: 12 }, { name: 'TypeScript', count: 8 }, { name: 'Rust', count: 2 }, { name: 'Shell', count: 1 }],
    package_managers: ['pnpm'],
    build_commands: ['pnpm build'], test_commands: ['pnpm test'], lint_commands: ['pnpm lint'], typecheck_commands: ['pnpm typecheck'],
    entrypoints: ['src/main.py'],
    existing: { 'AGENTS.md': false, 'CLAUDE.md': true },
  },
  diff: '--- /dev/null\n+++ AGENTS.md\n+# Atlas',
};

const body = (overrides: Partial<Parameters<typeof InitDialogBody>[0]> = {}) => renderToStaticMarkup(
  <InitDialogBody
    busy={false}
    applying={false}
    proposal={proposal}
    error={null}
    onApply={() => undefined}
    onClose={() => undefined}
    {...overrides}
  />,
);

describe('InitDialog', () => {
  it('shows the analysis state while the workspace is being scanned', () => {
    const html = body({ busy: true, proposal: null });
    expect(html).toContain('正在分析工作区');
    expect(html).not.toContain('写入 AGENTS.md');
  });

  it('previews a non-empty diff with scan chips and the write button', () => {
    const html = body();
    // 扫描摘要：语言取前 3 并注明总数、包管理、命令数量
    expect(html).toContain('语言：Python、TypeScript、Rust 等 4 种');
    expect(html).toContain('包管理：pnpm');
    expect(html).toContain('命令 4 条');
    expect(html).toContain('+# Atlas');
    expect(html).toContain('写入 AGENTS.md');
    expect(html).toContain('取消');
  });

  it('collapses to an up-to-date note with only a close button when the diff is empty', () => {
    const html = body({ proposal: { ...proposal, diff: '' } });
    expect(html).toContain('已是最新，无需写入。');
    expect(html).toContain('关闭');
    expect(html).not.toContain('写入 AGENTS.md');
    expect(html).not.toContain('+# Atlas');
  });

  it('surfaces backend errors (e.g. a rejected write) inside the dialog', () => {
    const html = body({ error: '磁盘上的 AGENTS.md 已被改过' });
    expect(html).toContain('磁盘上的 AGENTS.md 已被改过');
    expect(html).toMatch(/role="alert"/);
  });

  it('disables the write button while applying', () => {
    expect(body({ applying: true })).toMatch(/disabled="">[\s\S]*写入 AGENTS.md/);
  });
});
