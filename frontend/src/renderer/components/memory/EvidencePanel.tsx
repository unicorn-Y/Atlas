/**
 * EvidencePanel（T12.1）—— 「依据」解释面板。
 * GET /api/unified-memory/evidence/{record_ref}?revision=（契约 §6：原始定位与
 * 片段；删除后 410/屏障 423，不回落旧缓存）。展示原话/片段、时间、角色与
 * 推断标志；410 显示「已删除」，绝不拿页面里已有内容冒充依据。
 */
import { useEffect, useState } from 'react';
import { FileSearch, LoaderCircle } from 'lucide-react';
import { api } from '../../services/api';
import { Dialog } from '../../ui/Dialog';
import {
  epistemicLabel, formatMoment, isDeleted, locatorLabel, roleLabel, statusOf, str,
} from './common';

export interface EvidenceSnippet {
  text: string;
  occurredAt: string;
  speakerRole: string;
  inferred: boolean;
  epistemic: string;
  locatorKind: string;
  locatorValue: string;
  mediaAssetId: string;
  missing: string;
}

export class EvidenceDeletedError extends Error {
  readonly kind: 'deleted' | 'barrier';
  constructor(kind: 'deleted' | 'barrier', message: string) {
    super(message);
    this.name = 'EvidenceDeletedError';
    this.kind = kind;
  }
}

function normalizeSnippet(value: unknown): EvidenceSnippet {
  const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  const locator = (raw.locator && typeof raw.locator === 'object' ? raw.locator : {}) as Record<string, unknown>;
  const epistemic = str(raw.epistemic_kind);
  const text = str(raw.text ?? raw.quote ?? raw.verbatim ?? raw.content_text);
  return {
    text,
    occurredAt: str(raw.occurred_at ?? raw.observed_at ?? raw.valid_from),
    speakerRole: str(raw.speaker_role),
    inferred: raw.inferred === true || /INFERRED|DERIVED/i.test(epistemic),
    epistemic,
    locatorKind: str(locator.kind),
    locatorValue: str(locator.value),
    mediaAssetId: str(raw.asset_id ?? raw.media_asset_id),
    missing: str(raw.missing ?? raw.missing_reason),
  };
}

export function normalizeEvidence(payload: unknown): EvidenceSnippet[] {
  const snippets = (payload as { snippets?: unknown })?.snippets;
  if (!Array.isArray(snippets)) return [];
  return snippets.map(normalizeSnippet);
}

/** 410 → deleted（已删除）；423 → barrier（屏障处理中）；都不回落缓存。 */
function deletedKindOf(exc: unknown): 'deleted' | 'barrier' | null {
  if (isDeleted(exc)) return 'deleted';
  return statusOf(exc) === 423 ? 'barrier' : null;
}

/** record_ref 形如 episode:e-1 / memory:m-1：保留 : 与 /，只转义空格等危险字符。 */
export function evidencePath(recordRef: string): string {
  return recordRef.split('/').map((part) => encodeURIComponent(part).replace(/%3A/gi, ':')).join('/');
}

export async function fetchEvidence(
  apiBaseUrl: string,
  recordRef: string,
  opts: { revision?: number | null } = {},
): Promise<EvidenceSnippet[]> {
  const params = new URLSearchParams();
  if (opts.revision !== null && opts.revision !== undefined) params.set('revision', String(opts.revision));
  const query = params.toString();
  try {
    const payload = await api<unknown>(apiBaseUrl, `/api/unified-memory/evidence/${evidencePath(recordRef)}${query ? `?${query}` : ''}`);
    return normalizeEvidence(payload);
  } catch (exc) {
    const kind = deletedKindOf(exc);
    if (kind === 'deleted') throw new EvidenceDeletedError('deleted', '这条内容的原始记录已删除');
    if (kind === 'barrier') throw new EvidenceDeletedError('barrier', '原始记录暂时处于屏障处理中，稍后再试');
    throw exc;
  }
}

function SnippetRow({ snippet }: { snippet: EvidenceSnippet }) {
  const role = roleLabel(snippet.speakerRole);
  return <div style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
    <div className="chips" style={{ marginTop: 0, marginBottom: 8 }}>
      <span>{locatorLabel(snippet.locatorKind)}</span>
      {snippet.occurredAt && <span>{formatMoment(snippet.occurredAt)}</span>}
      {role && <span>说话：{role}</span>}
      {snippet.inferred && <span>推断</span>}
      {!snippet.inferred && epistemicLabel(snippet.epistemic) && <span>{epistemicLabel(snippet.epistemic)}</span>}
    </div>
    {snippet.missing && !snippet.text && <p className="empty-note" style={{ margin: 0 }}>原始内容缺失：{snippet.missing}</p>}
    {snippet.text && <blockquote style={{ margin: 0, padding: '8px 12px', borderLeft: '2px solid var(--line-strong)', color: 'var(--fg-2)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{snippet.text}</blockquote>}
    {snippet.locatorValue && <p className="empty-note" style={{ margin: '6px 0 0', overflowWrap: 'anywhere' }}>定位：{snippet.locatorValue}</p>}
  </div>;
}

/** 面板主体（同时用于静态测试渲染）。 */
export function EvidencePanelBody({ state }: { state: {
  loading: boolean;
  deleted: null | 'deleted' | 'barrier';
  error: string;
  snippets: EvidenceSnippet[];
  recordRef: string;
  revision: number | null;
} }) {
  return <div style={{ width: 'min(640px, calc(100vw - 32px))', maxHeight: 'min(640px, calc(100vh - 96px))', overflow: 'auto', padding: '18px 20px' }}>
    <h2 style={{ margin: '0 0 4px', font: '600 17px/1.4 var(--font-serif)', color: 'var(--heading)' }}>依据</h2>
    <p className="empty-note" style={{ margin: '0 0 8px', overflowWrap: 'anywhere' }}>
      {state.recordRef}{state.revision !== null ? ` · 版本 ${state.revision}` : ''}
    </p>

    {state.loading && <div className="empty" style={{ padding: '24px 0' }}><LoaderCircle size={20} className="spin" /><b>正在读取依据…</b></div>}

    {!state.loading && state.deleted === 'deleted' && <div className="empty" style={{ padding: '24px 0' }}>
      <FileSearch size={20} /><b>已删除</b>这条内容的原始记录已被删除，不再提供内容，也不会回落到旧缓存。
    </div>}
    {!state.loading && state.deleted === 'barrier' && <div className="empty" style={{ padding: '24px 0' }}>
      <FileSearch size={20} /><b>暂不可访问</b>原始记录正在屏障处理中（删除/导出对账），稍后再试。
    </div>}

    {!state.loading && !state.deleted && state.error && <div className="error-note" role="alert"><span>读取依据失败：{state.error}</span></div>}

    {!state.loading && !state.deleted && !state.error && state.snippets.length === 0 &&
      <div className="empty" style={{ padding: '24px 0' }}><FileSearch size={20} /><b>没有可展示的原始片段</b>服务端没有为这条记录返回依据。</div>}

    {!state.loading && !state.deleted && !state.error && state.snippets.map((snippet, index) => <SnippetRow key={index} snippet={snippet} />)}
  </div>;
}

export default function EvidencePanel({ apiBaseUrl, recordRef, revision, onClose }: {
  apiBaseUrl: string;
  recordRef: string;
  revision?: number | null;
  onClose: () => void;
}) {
  const [state, setState] = useState({ loading: true, deleted: null as null | 'deleted' | 'barrier', error: '', snippets: [] as EvidenceSnippet[] });
  useEffect(() => {
    let alive = true;
    fetchEvidence(apiBaseUrl, recordRef, { revision })
      .then((snippets) => { if (alive) setState({ loading: false, deleted: null, error: '', snippets }); })
      .catch((exc: unknown) => {
        if (!alive) return;
        if (exc instanceof EvidenceDeletedError) setState({ loading: false, deleted: exc.kind, error: '', snippets: [] });
        else setState({ loading: false, deleted: null, error: exc instanceof Error ? exc.message : String(exc), snippets: [] });
      });
    return () => { alive = false; };
  }, [apiBaseUrl, recordRef, revision]);

  return <Dialog open onOpenChange={(next) => { if (!next) onClose(); }} label="依据">
    <EvidencePanelBody state={{ ...state, recordRef, revision: revision ?? null }} />
  </Dialog>;
}
