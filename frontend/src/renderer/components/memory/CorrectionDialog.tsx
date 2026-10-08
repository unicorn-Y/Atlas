/**
 * CorrectionDialog（T12.1）—— 纠错对话框。
 * POST /api/unified-memory/corrections（契约 §6：request_id/target_ref/
 * expected_revision/replacement；幂等；不一致 409）。409 显示版本冲突提示
 * （不谎报成功）；成功显示受影响项。request_id 本地生成，重试沿用同一 id。
 */
import { useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { api } from '../../services/api';
import { Dialog } from '../../ui/Dialog';
import { statusOf, str } from './common';

export interface CorrectionInput {
  targetRef: string;
  expectedRevision: number | null;
  replacement: string;
  requestId?: string;
}

export interface CorrectionAffected {
  recordRef: string;
  reason: string;
}

export interface CorrectionResult {
  revision: number | null;
  affected: CorrectionAffected[];
}

export class CorrectionConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CorrectionConflictError';
  }
}

function newRequestId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch { /* 非安全上下文回落 */ }
  return `correction-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 归一化受影响项：兼容 [{record_ref,reason}] / 字符串数组 / 缺失。 */
export function normalizeAffected(payload: unknown): CorrectionAffected[] {
  const raw = (payload as { affected?: unknown; affected_items?: unknown })?.affected
    ?? (payload as { affected_items?: unknown })?.affected_items;
  if (!Array.isArray(raw)) return [];
  return raw.map((entry) => {
    if (typeof entry === 'string') return { recordRef: entry, reason: '' };
    if (entry && typeof entry === 'object') {
      const record = entry as Record<string, unknown>;
      return { recordRef: str(record.record_ref ?? record.ref ?? record.id), reason: str(record.reason ?? record.note) };
    }
    return { recordRef: '', reason: '' };
  }).filter((entry) => entry.recordRef);
}

export async function submitCorrection(
  apiBaseUrl: string,
  input: CorrectionInput,
): Promise<CorrectionResult> {
  const targetRef = input.targetRef.trim();
  const replacement = input.replacement.trim();
  if (!targetRef) throw new Error('缺少目标条目（target_ref）');
  if (!replacement) throw new Error('请填写更正后的内容');
  const requestId = input.requestId || newRequestId();
  let payload: unknown;
  try {
    payload = await api<unknown>(apiBaseUrl, '/api/unified-memory/corrections', {
      method: 'POST',
      json: {
        request_id: requestId,
        target_ref: targetRef,
        expected_revision: input.expectedRevision,
        replacement: { value: replacement },
        source: 'desktop-correction',
      },
    });
  } catch (exc) {
    if (statusOf(exc) === 409) {
      throw new CorrectionConflictError('版本冲突：这条内容刚被其他操作更新过。请关闭本窗口、刷新页面后再重试（内容不会被覆盖）。');
    }
    throw exc;
  }
  const record = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
  return {
    revision: typeof record.revision === 'number' ? record.revision : null,
    affected: normalizeAffected(payload),
  };
}

/** 对话框主体（静态可渲染，测试友好）。提交与关闭由父级管理。 */
export function CorrectionDialogBody({ targetRef, expectedRevision, replacement, onReplacementChange, busy, error, result, onSubmit, onClose }: {
  targetRef: string;
  expectedRevision: number | null;
  replacement: string;
  onReplacementChange: (value: string) => void;
  busy: boolean;
  error: string;
  result: CorrectionResult | null;
  onSubmit: () => void;
  onClose: () => void;
}) {
  return <div className="card glass" style={{ width: 'min(560px, calc(100vw - 32px))', maxHeight: 'min(640px, calc(100vh - 96px))', overflow: 'auto', margin: 0 }}>
    <h2>纠正这条记忆</h2>

    {result ? <>
      <p style={{ margin: '0 0 10px' }}>已提交更正{result.revision !== null ? `（新版本 ${result.revision}）` : ''}。</p>
      <div className="chips" style={{ marginBottom: 4 }}>
        {result.affected.length === 0 && <span>服务端没有列出受影响的其他条目</span>}
        {result.affected.map((entry) => <span key={entry.recordRef} title={entry.reason}>{entry.recordRef}{entry.reason ? `：${entry.reason}` : ''}</span>)}
      </div>
      {result.affected.length > 0 && <p className="empty-note">以上是随这次更正一起更新的相关条目。</p>}
      <div className="foot" style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
        <button className="btn primary" onClick={onClose} autoFocus>完成</button>
      </div>
    </> : <>
      <dl className="kv" style={{ margin: '0 0 12px' }}>
        <div><dt>目标条目</dt><dd title={targetRef}>{targetRef}</dd></div>
        <div><dt>依据版本</dt><dd>{expectedRevision === null ? '未知（按最新提交）' : `第 ${expectedRevision} 版`}</dd></div>
      </dl>
      <label style={{ display: 'grid', gap: 6, fontSize: 13, color: 'var(--fg-2)' }}>
        更正后的内容
        <textarea value={replacement} onChange={(event) => onReplacementChange(event.target.value)} rows={4}
          placeholder="写成应该记住的样子，例如：写代码用 VS Code，主题偏亮"
          aria-label="更正后的内容" disabled={busy} />
      </label>
      <p className="empty-note">提交后 Atlas 会把更正传播到相关记忆，并在时间线与回答里生效。</p>
      {error && <div className="error-note" role="alert"><span>{error}</span></div>}
      <div className="foot" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
        <button className="btn ghost" onClick={onClose} disabled={busy}>取消</button>
        <button className="btn primary" onClick={onSubmit} disabled={busy || !replacement.trim()}>
          {busy ? <LoaderCircle size={14} className="spin" /> : null}提交纠错
        </button>
      </div>
    </>}
  </div>;
}

export default function CorrectionDialog({ apiBaseUrl, targetRef, expectedRevision, onClose, onCorrected }: {
  apiBaseUrl: string;
  targetRef: string;
  expectedRevision?: number | null;
  onClose: () => void;
  onCorrected?: (result: CorrectionResult) => void;
}) {
  const [replacement, setReplacement] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CorrectionResult | null>(null);

  const submit = async () => {
    setBusy(true); setError('');
    try {
      const done = await submitCorrection(apiBaseUrl, { targetRef, expectedRevision: expectedRevision ?? null, replacement });
      setResult(done);
      onCorrected?.(done);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setBusy(false); }
  };

  return <Dialog open onOpenChange={(next) => { if (!next && !busy) onClose(); }} label="纠正这条记忆">
    <CorrectionDialogBody
      targetRef={targetRef}
      expectedRevision={expectedRevision ?? null}
      replacement={replacement}
      onReplacementChange={setReplacement}
      busy={busy}
      error={error}
      result={result}
      onSubmit={() => void submit()}
      onClose={onClose}
    />
  </Dialog>;
}
