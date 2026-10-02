import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ComponentProps } from 'react';
import ReviewFindingsCard, { FindingRow, fixMessage, formatFinding, findingWhere } from './ReviewFindingsCard';
import type { TimelineItem } from './timeline';

type CardProps = ComponentProps<typeof ReviewFindingsCard>;
type Finding = Extract<TimelineItem, { kind: 'review' }>['findings'][number];
const store = { sendMessage: vi.fn(async () => undefined) } as unknown as CardProps['store'];

const item = (findings: Finding[]): Extract<TimelineItem, { kind: 'review' }> =>
  ({ kind: 'review', id: 'r1', scope: 'working_tree', scopeLabel: '当前未提交改动', workspace: 'C:/ws', findings });

const finding: Finding = {
  file: 'src/app.py', line: 12, range: [12, 20], severity: 'blocker',
  title: '空指针', explanation: 'x 可能为 None', evidence: 'x = maybe()\nx.foo()', suggested_fix: '先判空再取属性',
};

describe('ReviewFindingsCard', () => {
  it('renders the header with per-severity counts, muted zero chips, and one row per finding', () => {
    const html = renderToStaticMarkup(
      <ReviewFindingsCard item={item([{ ...finding }, { ...finding, file: 'src/b.py', line: null, severity: 'minor', title: '命名' }])} store={store} />,
    );
    expect(html).toContain('代码审查 · 当前未提交改动');
    expect(html).toContain('阻断');
    expect(html).toContain('主要');
    expect(html).toContain('次要');
    // 三个计数徽标里只有为 0 的那一个（主要 0）带弱化样式
    expect((html.match(/opacity-40/g) ?? []).length).toBe(1);
    expect(html).toContain('src/app.py:12');
    expect(html).toContain('空指针');
    expect(html).toContain('src/b.py');
    // 行默认折叠，「打开文件」按钮在展开区里，静态整卡渲染看不到（见下方 FindingRow 用例）
    expect(html).not.toContain('打开文件');
  });

  it('offers the internal open-file action in an expanded row when a workspace is set', () => {
    const row = (workspace: string) => renderToStaticMarkup(
      <FindingRow finding={finding} store={store} workspace={workspace} defaultOpen />,
    );
    // 打开文件走 Atlas 内部文件面板并定位行，只依赖 workspace，不再需要桌面通道
    expect(row('C:/ws')).toContain('打开文件');
    expect(row('')).not.toContain('打开文件');
  });

  it('shows a success card when the findings array is empty', () => {
    const html = renderToStaticMarkup(<ReviewFindingsCard item={item([])} store={store} />);
    expect(html).toContain('没有发现问题');
    expect(html).not.toContain('全部发回对话修复');
  });

  it('expands a finding into explanation, clipped evidence and the suggested fix', () => {
    // renderToStaticMarkup 走不到 useState 的交互态；直接验证纯文本格式化函数与静态部分。
    expect(findingWhere(finding)).toBe('src/app.py:12');
    expect(formatFinding(finding, 0)).toBe('1. [阻断] src/app.py:12 空指针\n   说明：x 可能为 None\n   证据：x = maybe()\nx.foo()\n   建议修法：先判空再取属性');
    expect(fixMessage(finding)).toBe('请修复代码审查发现的这个问题：\n文件：src/app.py:12\n标题：空指针\n说明：x 可能为 None\n证据：x = maybe()\nx.foo()\n建议修法：先判空再取属性');
    expect(findingWhere({ ...finding, line: null })).toBe('src/app.py');
  });
});
