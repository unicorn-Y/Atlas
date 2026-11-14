import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import UltraplanPanel from './UltraplanPanel';

vi.mock('../services/api', () => ({ api: vi.fn() }));
vi.mock('../ui/Dialog', () => ({ Dialog: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <section role="dialog">{children}</section> : null }));

afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });

describe('UltraplanPanel review and approval', () => {
  it('loads the generated plan, saves edited steps and approves only after saving', async () => {
    const job = { id: 'plan-1', status: 'awaiting_approval', path: 'plans/change.md', progress: [], plan: {
      goal: 'Ship the change', background: 'Existing code', steps: [{ id: 's1', title: 'Implement', detail: 'Change code', files: ['src/a.ts'], verify: 'Run tests' }], risks: ['Regression'], open_questions: [],
    } };
    vi.stubGlobal('window', { setInterval: vi.fn(), clearInterval: vi.fn() });
    vi.mocked(api).mockImplementation(async (_base, path, init) => {
      if (path.endsWith('/approve')) return { ...job, status: 'executing' } as never;
      if (init?.method === 'PUT') return { ...job, plan: (init.json as { plan: unknown }).plan } as never;
      return job as never;
    });
    const onOpenArtifact = vi.fn();
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<UltraplanPanel open goal="Ship the change" workspace="D:/project" conversationId="session-1" model="test-model"
      apiBaseUrl="http://127.0.0.1:8876" onClose={vi.fn()} onToast={vi.fn()} onOpenArtifact={onOpenArtifact} />); });
    expect(onOpenArtifact).toHaveBeenCalledWith('plans/change.md', 'Ship the change');
    expect(view.root.findByProps({ 'aria-label': '步骤详情' }).props.value).toBe('Change code');
    act(() => { view.root.findByProps({ 'aria-label': '步骤标题' }).props.onChange({ target: { value: 'Write regression first' } }); });
    const annotation = view.root.findAllByType('label').find((label) => label.children.includes('步骤批注'))!.findByType('textarea');
    act(() => { annotation.props.onChange({ target: { value: 'Cover the old failure' } }); });
    const approve = view.root.findAllByType('button').find((button) => button.children.includes('批准并执行'))!;
    await act(async () => { approve.props.onClick(); });
    const calls = vi.mocked(api).mock.calls;
    const saveIndex = calls.findIndex(([, path, init]) => path === '/api/ultraplan/plan-1' && init?.method === 'PUT');
    const approveIndex = calls.findIndex(([, path]) => path.endsWith('/approve'));
    expect(saveIndex).toBeGreaterThanOrEqual(0);
    expect(approveIndex).toBeGreaterThan(saveIndex);
    expect(calls[saveIndex][2]?.json).toMatchObject({ plan: { steps: [{ title: 'Write regression first', annotation: 'Cover the old failure' }] } });
    act(() => view.unmount());
  });
});
