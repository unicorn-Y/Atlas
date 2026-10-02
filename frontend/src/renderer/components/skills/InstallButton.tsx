import { useState } from 'react';
import { AlertTriangle, Check, Download, LoaderCircle } from 'lucide-react';
import { installSkill, isMarketConflictError, type InstallScope } from '../../services/skillsMarketApi';

/** 409 冲突时弹出的中文确认框：说明同名冲突，由用户决定是否覆盖安装。 */
export function ConflictDialog({ name, busy, onCancel, onOverwrite }: {
  name: string;
  busy?: boolean;
  onCancel: () => void;
  onOverwrite: () => void;
}) {
  return <div role="dialog" aria-modal="true" aria-label="同名技能冲突" className="fixed inset-0 z-50 grid place-items-center bg-black/35 p-6"
    onClick={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <div className="card-surface w-full max-w-[400px] rounded-2xl p-5">
      <h3 className="m-0 flex items-center gap-2 text-[15px] font-semibold text-heading"><AlertTriangle size={17} className="text-danger" />已有一个同名的技能</h3>
      <p className="mb-4 mt-2 text-[13px] leading-relaxed text-fg-2">
        本地已经安装过「{name}」。默认不会动它。如果你确认要用市场里的版本替换本地文件，可以选择覆盖安装；本地版本会被替换，操作前请确认它没有你自己的修改。
      </p>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn ghost" disabled={busy} onClick={onCancel}>先不装了</button>
        <button type="button" className="btn danger" disabled={busy} onClick={onOverwrite}>
          {busy ? <LoaderCircle size={15} className="spin" /> : null}覆盖安装
        </button>
      </div>
    </div>
  </div>;
}

const SCOPE_LABEL: Record<InstallScope, string> = { user: '装到用户目录', project: '装到当前项目' };

/** 安装按钮：处理忙碌、失败重试与 409 同名冲突（冲突弹中文确认框后可覆盖安装）。 */
export default function InstallButton({ apiBaseUrl, source, id, scope, onInstalled, size = 'md' }: {
  apiBaseUrl: string;
  source: string;
  id: string;
  scope: InstallScope;
  onInstalled?: (id: string) => void;
  size?: 'sm' | 'md';
}) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);

  const run = async (overwrite: boolean) => {
    setBusy(true);
    setError('');
    try {
      await installSkill(apiBaseUrl, { source, id, scope, overwrite });
      setDone(true);
      setConflict(false);
      onInstalled?.(id);
    } catch (cause) {
      if (isMarketConflictError(cause)) { setConflict(true); setError(''); }
      else setError(cause instanceof Error ? cause.message : '安装没有成功，请稍后再试。');
    } finally { setBusy(false); }
  };

  const cls = size === 'sm' ? 'btn h-7 px-2.5 text-[12px]' : 'btn primary';
  if (done) return <span className="btn h-7 px-2.5 text-[12px]" aria-live="polite"><Check size={15} />已安装</span>;
  return <>
    <button type="button" className={cls} disabled={busy} title={SCOPE_LABEL[scope]} onClick={() => void run(false)}>
      {busy ? <LoaderCircle size={15} className="spin" /> : <Download size={15} />}{busy ? '正在安装…' : size === 'sm' ? '安装' : '安装技能'}
    </button>
    {error && <span role="alert" className="text-[12px] text-danger">{error}</span>}
    {conflict && <ConflictDialog name={id} busy={busy} onCancel={() => setConflict(false)} onOverwrite={() => void run(true)} />}
  </>;
}
