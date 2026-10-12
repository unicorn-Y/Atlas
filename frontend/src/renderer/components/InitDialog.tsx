import { useShallow } from 'zustand/react/shallow';
import { FileText, Languages, LoaderCircle, Package, TerminalSquare } from 'lucide-react';
import type { InitProposal } from '@atlas/backend-adapter';
import { useAtlasStore } from '../store/useAtlasStore';
import { DiffView } from '../shell/panels/ChangesPanel';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';

/** 扫描摘要的小徽标。 */
function Chip({ icon, label }: { icon: React.ReactNode; label: string }) {
  return <span className="inline-flex items-center gap-1.5 rounded-full bg-sunken px-2.5 py-1 text-[12px] text-fg-2">{icon}{label}</span>;
}

/** InitDialog 的内容（不含 Radix Portal，方便单独渲染/测试）。 */
export function InitDialogBody({ busy, applying, proposal, error, onApply, onClose }: {
  busy: boolean; applying: boolean; proposal: InitProposal | null; error: string | null;
  onApply: () => void; onClose: () => void;
}) {
  if (busy) {
    return <div className="flex items-center gap-3 px-6 py-8 text-[13.5px] text-fg-2">
      <LoaderCircle size={17} className="spin shrink-0 text-brand" />正在分析工作区，整理现有的规则文件…
    </div>;
  }
  if (!proposal) {
    return <div className="grid gap-4 px-6 py-6">
      {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">{error}</p>}
      <div className="flex justify-end"><Button onClick={onClose}>关闭</Button></div>
    </div>;
  }
  const scan = proposal.scan;
  const languages = scan.languages.slice(0, 3).map((item) => item.name).join('、');
  const commandCount = scan.build_commands.length + scan.test_commands.length + scan.lint_commands.length + scan.typecheck_commands.length;
  const upToDate = !proposal.diff.trim();
  return <div className="grid gap-4 px-6 pb-6 pt-5">
    <div>
      <h2 className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><FileText size={17} className="text-brand" />AGENTS.md</h2>
      <p className="m-0 mt-1 truncate font-mono text-[12px] text-fg-3" title={proposal.path}>{proposal.path}</p>
      <p className="m-0 mt-2 text-[12px] leading-5 text-fg-3">
        目标是当前工作区根目录。受信任工作区中的 CLAUDE.md 也可作为项目指令读取；此操作只写入上方的 AGENTS.md 路径，请先核对预览差异。
      </p>
    </div>
    <div className="flex flex-wrap gap-1.5">
      {languages && <Chip icon={<Languages size={13} className="shrink-0 text-fg-3" />} label={`语言：${languages}${scan.languages.length > 3 ? ` 等 ${scan.languages.length} 种` : ''}`} />}
      {scan.package_managers.length > 0 && <Chip icon={<Package size={13} className="shrink-0 text-fg-3" />} label={`包管理：${scan.package_managers.join('、')}`} />}
      {commandCount > 0 && <Chip icon={<TerminalSquare size={13} className="shrink-0 text-fg-3" />} label={`命令 ${commandCount} 条（构建/测试/检查/类型）`} />}
    </div>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">{error}</p>}
    {upToDate
      ? <p className="m-0 rounded-xl bg-ok-soft px-4 py-3 text-[13px] text-ok">已是最新，无需写入。</p>
      : <div className="overflow-hidden rounded-xl shadow-[inset_0_0_0_1px_var(--line)]">
        <DiffView diff={proposal.diff} path={proposal.path || 'AGENTS.md'} onAdd={() => undefined} onEdit={() => undefined} onRemove={() => undefined} />
      </div>}
    <div className="flex items-center justify-end gap-2">
      {upToDate
        ? <Button variant="ghost" onClick={onClose}>关闭</Button>
        : <>
          <Button variant="ghost" onClick={onClose} disabled={applying}>取消</Button>
          <Button variant="primary" onClick={onApply} disabled={applying}>
            {applying && <LoaderCircle size={14} className="spin" />}写入 AGENTS.md
          </Button>
        </>}
    </div>
  </div>;
}

/** /init 的对话框：扫描摘要 + 提案 diff，确认后写入 AGENTS.md。App 常驻挂载，由 store 的 initOpen 控制显隐。 */
export default function InitDialog({ onToast }: { onToast?: (text: string) => void }) {
  const { open, busy, applying, proposal, error, applyInit, closeInit } = useAtlasStore(useShallow((state) => ({
    open: state.initOpen, busy: state.initBusy, applying: state.initApplying, proposal: state.initProposal, error: state.initError,
    applyInit: state.applyInit, closeInit: state.closeInit,
  })));
  const apply = async () => {
    // 写入成功时 store 会关掉对话框；这里只负责把结果 toast 出来。
    if (await applyInit()) onToast?.('AGENTS.md 已写入');
  };
  return <Dialog open={open} onOpenChange={(value) => { if (!value) closeInit(); }} label="AGENTS.md 提案"
    className="w-[min(720px,calc(100vw-32px))] rounded-2xl">
    <InitDialogBody busy={busy} applying={applying} proposal={proposal} error={error} onApply={() => void apply()} onClose={closeInit} />
  </Dialog>;
}
